# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import csv
from utils.log import get_logger
from utils.constants import ACCOUNT_ID_LENGTH
from botocore.exceptions import ClientError

LOGGER = get_logger(__name__)

class ValidationException(Exception):
    """
    Thrown when validations fail
    """
    pass

def read_accounts_from_file(file_path):
    """
    Read CSV file containing AWS Account IDs and return the list of accounts
    """
    try:
        accounts = []
        LOGGER.info(f"Reading accounts from file: {file_path}")
        with open(file_path, 'r', encoding="utf-8") as fp:
            rows = csv.reader(fp)
            for row in rows:
                # Skip empty rows
                if not ''.join(row).strip():
                    continue
                account_id = row[0]
                if is_valid_account_id(account_id):
                    accounts.append(account_id)
                else:
                    raise ValidationException(
                        f"Invalid data in file {file_path}.\nThe file should contain only 12 digit AWS Account IDs")
        return accounts
    except Exception as err:
        LOGGER.error(f"Failed when reading accounts from file: {file_path}")
        raise err

def write_accounts_to_file(accounts):
    """
    Write the list of AWS Account IDs to the specified file
    """
    file_path = "accounts.csv"
    try:
        LOGGER.info(f"Writing accounts to file: {file_path}")
        with open(file_path, 'w', encoding="utf-8", newline ='') as fp:
            writer = csv.writer(fp)
            for account in accounts:
                writer.writerow([account])
    except Exception as err:
        LOGGER.error(f"Failed when writing accounts to file: {file_path}")
        raise err

def read_regions_from_file(file_path):
    """
    Read CSV file containing specific AWS Regions to use and return the list of regions
    """
    try:
        regions = []
        LOGGER.info(f"Reading regions from file: {file_path}")
        with open(file_path, 'r', encoding="utf-8") as fp:
            rows = csv.reader(fp)
            for row in rows:
                # Skip empty rows
                if not ''.join(row).strip():
                    continue
                region = row[0]
                regions.append(region)
        return regions
    except Exception as err:
        LOGGER.error(f"Failed when reading regions from file: {file_path}")
        raise err

def write_regions_to_file(regions):
    """
    Write the list of AWS Regions to the specified file
    """
    file_path = "regions.csv"
    try:
        LOGGER.info(f"Writing regions to file: {file_path}")
        with open(file_path, 'w', encoding="utf-8", newline ='') as fp:
            writer = csv.writer(fp)
            for region in regions:
                writer.writerow([region])
    except Exception as err:
        LOGGER.error(f"Failed when writing regions to file: {file_path}")
        raise err

def is_china_region(boto_client):
    """
    Return a boolean value indicating whether the region is China or not.
    """
    return boto_client.meta.partition == 'aws-cn'

def is_valid_account_id(account_id):
    return account_id.isnumeric() and len(account_id) == ACCOUNT_ID_LENGTH

def _validate_account(account_id):
    if is_valid_account_id(account_id) is not True:
        raise ValidationException(f'Invalid input: {account_id} must be a 12 digit numeric string')


def get_all_org_accounts(org_client_):
        """ Returns all ACTIVE accounts in the organization """
        result = []
        response = org_client_.list_accounts()
        active_accounts = list(filter(lambda x: x['Status'] == 'ACTIVE', response['Accounts']))
        result.extend(list(map(lambda x: x['Id'], active_accounts)))
        while 'NextToken' in response and response['NextToken']:
            response = org_client_.list_accounts(NextToken=response['NextToken'])
            active_accounts = list(filter(lambda x: x['Status'] == 'ACTIVE', response['Accounts']))
            result.extend(list(map(lambda x: x['Id'], active_accounts)))
        return result

def validate_org_accounts(input_accounts, payer_account, all_member_accounts):
    # validate accounts passed in are member accounts in payer's org
    for account in input_accounts:
        if account not in all_member_accounts:
            raise ValidationException(
                f"Invalid input: {account} is not a member of payer ({payer_account}) org")


def validate_if_being_run_by_payer_account(org_client, caller_account):
    """ Validate that the script is being run by payer account """
    try:
        response = org_client.describe_organization()
        management_account = response["Organization"]["MasterAccountId"]
        if caller_account != management_account:
            LOGGER.error("Script being run by a member account of AWS organization")
            raise ValidationException("Script can only be run by management account of an AWS Organization")

    except ClientError as err:
        if err.response["Error"]["Code"] == "AWSOrganizationsNotInUseException":
            LOGGER.error("Script being run by an account which is not part of an AWS Organization")
            raise ValidationException("Script can only be run by management account of an AWS Organization")
        else:
            raise err
    except Exception as err:
        LOGGER.error("Failed calling Organization DescribeOrganization API")
        raise err