# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import sys
import uuid
import json
import boto3
import argparse
import threading 
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from botocore.exceptions import ClientError

''' Supress the following
DeprecationWarning: 
Pyarrow will become a required dependency of pandas in the next major release of pandas (pandas 3.0),
(to allow more performant data types, such as the Arrow string type, and better interoperability with other libraries)
but was not found to be installed on your system.
If this would cause problems for you,
please provide us feedback at https://github.com/pandas-dev/pandas/issues/54466
'''
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning) 
import pandas as pd

from utils.utils import (
    is_china_region, 
    validate_if_being_run_by_payer_account, 
    validate_org_accounts,
    get_all_org_accounts,
    read_accounts_from_file,
    write_accounts_to_file,
    write_regions_to_file
) 

from utils.utils import ValidationException
from utils.log import get_logger
from utils.constants import MEMBER_ACCOUNT_ROLE_NAME
from utils.rds_mappings import (
    is_extended_support_eligible,
    get_rds_instance_mapping,
    get_rds_extended_support_pricing,
    get_rds_regions
)

LOGGER = get_logger(__name__)

''' Build some local caches for -  
    1. RDS Regions
    2. RDS Instance Mapping
    3. Cache for storing processed account IDs  
'''
REGIONS = {}
DB_INSTANCE_MAPPING = {}

processed_accounts = []
try:
    # Try to load processed accounts from cache file
    with open('.tmp_accounts_cache.json', encoding="utf-8") as f:
        processed_accounts = json.load(f)
        LOGGER.info(f'Found a previous cache file with {len(processed_accounts)} accounts aready processed. Continuing with remaining accounts...')
except:
    pass

# Use a thread lock  
lock = threading.Lock()

# check if `output` directory exists in current working dir, if not create it.
if not os.path.isdir('./output'):
    LOGGER.debug("'output' folder does not exist, creating it now")
    os.makedirs('./output')

# create a filename using today's date time in YY-MM-DD HH-MM format
outfile = f'./output/rds_extended_support_instances-{datetime.now().strftime("%Y-%m-%d %H-%M")}.csv'
LOGGER.info("Outfile name: {}".format(outfile))


def get_rds_client(account_id_, payer_account_, region_, assume_role=MEMBER_ACCOUNT_ROLE_NAME):
    if account_id_ == payer_account_:
        LOGGER.debug("Running for Payer account, returning rds boto3 client")
        rds_client = boto3.client('rds', region_name=region_)
    else:
        LOGGER.debug("Running for Linked account, assuming custom role and returning rds boto3 client after extracting credentials")
        sts_client = boto3.client('sts')
        partition = sts_client.meta.partition
        assumed_role_object = sts_client.assume_role(
            RoleArn=f'arn:{partition}:iam::{account_id_}:role/{assume_role}',
            RoleSessionName=f'AssumeRoleSession{uuid.uuid4()}'
        )
        credentials = assumed_role_object['Credentials']
        rds_client = boto3.client(
            'rds',
            region_name=region_,
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
        )
    return rds_client

# Iterate through all rds instances and return details including current rds version
def get_rds_instances(rds_client):
    rds_instances = []
    paginator = rds_client.get_paginator('describe_db_instances')
    try:
        for page in paginator.paginate(Filters=[{'Name': 'engine', 'Values':['aurora-postgresql', 'aurora-mysql', 'mysql', 'postgres']}]):
            for instance in page['DBInstances']:
                rds_instances.append(instance)
    except ClientError as err:
        if err.response["Error"]["Code"] == "InvalidClientTokenId":
            LOGGER.error("Received InvalidClientTokenId error - perhaps Region {} is not enabled for the account. Skipping region ...".format(rds_client.meta.region_name))
            #raise ValidationException("Script can only be run in regions that have been enabled")
        else:
            raise err
    except Exception as err:
        LOGGER.error("Failed calling RDS DescribeDBInstances API")
        raise err
    return rds_instances

def get_rds_extended_support_instances(account_id, caller_account):
    global DB_INSTANCE_MAPPING
    keys = ['DBInstanceIdentifier', 'DBInstanceClass', 'Engine', 'EngineVersion', 'DBInstanceStatus', 'MultiAZ', 'DBInstanceArn']
    rds_extended_support_instances = []
    
    #### OVERRIDE - FOR TESTING ###
    #REGIONS = {'us-east-1':'US East (N. Virginia)', 'us-west-2': 'US West (Oregon)', 'eu-west-1': 'Europe (Ireland)'}
    #### OVERRIDE - FOR TESTING ###

    #TODO: Handle Aurora Serverless v2 instances 
    for region in REGIONS:
        LOGGER.info(f'Running for account {account_id} in region {region}')
        rds_client = get_rds_client(account_id, caller_account, region)
        rds_instances = get_rds_instances(rds_client)
        LOGGER.info(f'Found {len(rds_instances)} RDS instances in account {account_id} in region {region}')

        for instance in rds_instances:
            LOGGER.debug(f'==> Instance: {instance}')
            if is_extended_support_eligible(instance):
                LOGGER.debug(f'Instance is eligible for extended support')
                shortlist_instance = {key: instance[key] for key in keys}
                shortlist_instance['AccountId'] = account_id
                shortlist_instance['Region'] = region
                shortlist_instance['RegionName'] = REGIONS[region]
                # Handle the case where an instance type is not found in rds_instance_mapping.json (perhaps its a new family/size added)
                # We will just regenrate the entire mapping by scrapping the AWS Documentation HTML page. 
                if shortlist_instance['DBInstanceClass'] not in DB_INSTANCE_MAPPING:
                    LOGGER.error(f'Instance type {shortlist_instance["DBInstanceClass"]} not found in rds_instance_mapping.json. Regenerating json file from AWS documentation')
                    DB_INSTANCE_MAPPING = get_rds_instance_mapping()
                    LOGGER.info(f'Updated DB Instance Mapping: {DB_INSTANCE_MAPPING}')
                shortlist_instance['vCPUs per instance'] = DB_INSTANCE_MAPPING[shortlist_instance['DBInstanceClass']]

                rds_extended_support_instances.append(shortlist_instance)

    LOGGER.info(f'RDS Extended Support Eligible Instances: \n {rds_extended_support_instances}')
    
    with lock:
        save_to_csv(rds_extended_support_instances)
        processed_accounts.append(account_id)
        with open('.tmp_accounts_cache.json', 'w', encoding="utf-8") as f:
            json.dump(processed_accounts, f)
        
        LOGGER.info(f'Saved eligible RDS instances in all regions from {account_id} to csv file, and added account to cache file')


def save_to_csv(rds_extended_support_instances):
    
    def get_total_vcpus(row):
        return 2*int(row['vCPUs per instance']) if row['MultiAZ'] == True else int(row['vCPUs per instance'])
    
    def get_y1_price(row):
        (provisioned_price_map, _) = get_rds_extended_support_pricing(row['Engine'].split('-')[0])
        region_name = row['Region']
        yr_1_2_price = provisioned_price_map[region_name]['yr_1_2_price']
        return row['Total vCPUs (if MultiAZ)'] * yr_1_2_price * 24 * 365 # extended support price is per vCPU-hour
    def get_y3_price(row):
        (provisioned_price_map, _) = get_rds_extended_support_pricing(row['Engine'].split('-')[0])
        region_name = row['Region']
        '''
        Per the Amazon RDS Aurora pricing page (https://aws.amazon.com/rds/aurora/pricing/#Amazon_RDS_Extended_Support_costs)
        Amazon RDS Extended Support year 3 pricing is only available for Amazon Aurora PostgreSQL-Compatible Edition.
        Extended Support for Amazon Aurora MySQL comptible engine is charged at Year 1 prices for the entire duration 
        of Extended Support for the respective major version.
        '''
        if ("mysql_aurora.2.11" in row['EngineVersion']) or ("mysql_aurora.2.12" in row['EngineVersion']):
            yr_3_price = provisioned_price_map[region_name]['yr_1_2_price']
        else:
            yr_3_price = provisioned_price_map[region_name]['yr_3_price']
        return row['Total vCPUs (if MultiAZ)'] * yr_3_price * 24 * 365 # extended support price is per vCPU-hour
    
    if len(rds_extended_support_instances) == 0:
        LOGGER.info('No RDS instances are eligible for extended support. Not writing anything to CSV for this account')
        return

    df = pd.DataFrame.from_dict(rds_extended_support_instances)
    
    df['Total vCPUs (if MultiAZ)'] = df.apply(lambda row: get_total_vcpus(row), axis=1)
    df['Year 1 Price'] = df.apply(lambda row: get_y1_price(row), axis=1)
    df['Year 1 Price'] = df['Year 1 Price'].apply(lambda x: "${0:,.2f}".format(x))
    df['Year 2 Price'] = df['Year 1 Price']
    df['Year 3 Price'] = df.apply(lambda row: get_y3_price(row), axis=1)
    df['Year 3 Price'] = df['Year 3 Price'].apply(lambda x: "${0:,.2f}".format(x))
    #df.loc['Total'] = pd.Series(df['Year 1 Price'].sum(), index=['Year 1 Price'])
    #print(df.head())

    df.to_csv(outfile, mode='a', index=False, header=False)

    #TODO: Add more details about dates for EoS, Start of Y1, Y3 Extended Suport price etc.


def main():
    global REGIONS
    global DB_INSTANCE_MAPPING
    args = parse_args()
    sts_client = boto3.client('sts')
    org_client = boto3.client('organizations')
    LOGGER.info("Running with boto client region = %s", sts_client.meta.region_name)
    
    caller_account = sts_client.get_caller_identity()['Account']
    is_china = is_china_region(sts_client)
    validate_if_being_run_by_payer_account(org_client, caller_account)
    LOGGER.info(f'Caller account: {caller_account}')

    # Check if the mapping file exists, if it does, read from it
    try:
        # Try to load rds instane mapping json file
        with open('rds_instance_mapping.json') as f:
            DB_INSTANCE_MAPPING = json.load(f)
            LOGGER.debug(f'Read RDS db instance mapping from file rds_instance_mapping.json')
    except:
        LOGGER.debug("No RDS db instance mapping file found, getting mapping from AWS Pricing page")
        DB_INSTANCE_MAPPING = get_rds_instance_mapping()

    REGIONS = get_rds_regions(args.regions_file)
    if args.generate_regions_file:
        write_regions_to_file(REGIONS)
        LOGGER.info(f'Saved RDS regions to file: regions.csv. Script will ignore any other inputs and exit.')
        sys.exit(0)

    if args.generate_accounts_file:
        account_pool = get_all_org_accounts(org_client)
        write_accounts_to_file(account_pool)
        LOGGER.info(f'Saved AWS Accounts in Organization to file: accounts.csv. Script will ignore any other inputs and exit.')
        sys.exit(0) 

    if args.all:
        LOGGER.info(f'Running in ORG mode for payer account: {caller_account}')
        account_pool = get_all_org_accounts(org_client)
        if args.exclude_accounts:
            LOGGER.info(f'Excluding accounts: {args.exclude_accounts}')
            exclude_accounts = [account.strip() for account in args.exclude_accounts.split(",")]
            for account in exclude_accounts:
                if account in account_pool:
                    account_pool.remove(account)
    elif args.accounts:
        if args.exclude_accounts:
            raise ValidationException('Invalid input: cannot use --exclude-accounts with --accounts argument')
        account_pool = [s.strip() for s in args.accounts.split(',')]
        all_org_accounts = get_all_org_accounts(org_client)
        validate_org_accounts(account_pool, caller_account, all_org_accounts)
        LOGGER.info(f'Running in LINKED ACCOUNT mode with accounts: {account_pool}')
    elif args.accounts_file:
        if args.exclude_accounts:
            raise ValidationException('Invalid input: cannot use --exclude-accounts with --accounts-file argument')
        account_pool = read_accounts_from_file(args.accounts_file)
        all_org_accounts = get_all_org_accounts(org_client)
        validate_org_accounts(account_pool, caller_account, all_org_accounts)
        LOGGER.info(f'Running in LINKED ACCOUNT mode with accounts: {account_pool}')
    else:
        LOGGER.info(f'Running in PAYER ACCOUNT mode for payer account: {caller_account}')
        account_pool = [caller_account]

    LOGGER.info(f'Running in specific regions: {REGIONS}')

    df = pd.DataFrame(columns=['DBInstanceIdentifier', 'DBInstanceClass', 'Engine', 'EngineVersion', 'DBInstanceStatus', 'MultiAZ', 'DBInstanceArn', 'AccountId', 'Region', 'RegionName', 'vCPUs per instance', 'Total vCPUs (if MultiAZ)', 'Year 1 Price', 'Year 2 Price', 'Year 3 Price' ])
    df.to_csv(outfile, index=False)
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = { executor.submit(get_rds_extended_support_instances, account, caller_account) 
                   for account in account_pool 
                   if account not in processed_accounts }
        # Catch a thread's exceptions, if any, in the main thread
        # https://docs.python.org/3.7/library/concurrent.futures.html#concurrent.futures.as_completed
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                LOGGER.error(f"Error in processing account. Exception: {e}")
                raise


    LOGGER.info("="*25)
    LOGGER.info(f'Saved Final results to CSV file: {outfile} and deleting cached data')
    LOGGER.info("Script Execution Completed Successfully!")
    LOGGER.info("="*25)
    
    # If we have reached this point, script has been successfully executed for all accounts & regions. 
    # So, delete the .tmp_accounts_cache.json file.
    if os.path.exists('.tmp_accounts_cache.json'):
        os.remove('.tmp_accounts_cache.json')

 

def parse_args():
    arg_parser = argparse.ArgumentParser()
    
    group = arg_parser.add_mutually_exclusive_group()
    group.add_argument('-a', '--accounts', help='comma separated list of AWS account IDs', type=str)
    group.add_argument('--accounts-file', help='Absolute path of the CSV file containing AWS account IDs', type=str)
    group.add_argument('--all', help="runs script for the entire AWS Organization", action='store_true')

    arg_parser.add_argument('--regions-file', help='Absolute path of the CSV file containing specific AWS regions to run the script against', type=str)
    arg_parser.add_argument(
        '--exclude-accounts',
        help='comma separated list of AWS account IDs to be excluded, only applies when --all flag \
            is used', type=str
    )

    arg_parser.add_argument('--generate-accounts-file', help='Creates a `accounts.csv` CSV file containing all AWS accounts in the AWS Organization', action='store_true')
    arg_parser.add_argument('--generate-regions-file', help='Creates a `regions.csv` CSV file containing all AWS regions', action='store_true')

    args = arg_parser.parse_args()
    return args

if __name__ == '__main__':
    main()