# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import json
import requests
from bs4 import BeautifulSoup
from utils.log import get_logger
from utils.utils import read_regions_from_file
from utils.utils import ValidationException

LOGGER = get_logger(__name__)

AURORA_EXTENDED_SUPPORT_VERSION = {
        "mysql-5.7":{
            "aurora-major-version": "mysql-aurora-2",
            "community-eol-date": "10-31-2023",
            "rds-standard-eos-date": "10-31-2024",
            "rds-extended-support-yr1-stat-date": "12-01-2024",
            "rds-extended-support-yr3-stat-date": "N/A",
            "rds-extended-eos-date": "02-28-2025",
            "minor-versions-eligible-extended-support": ["mysql_aurora-2.11", "mysql_aurora-2.12"]
        },
        "postgres-11": {
            "aurora-major-version": "postgres-aurora-3",
            "community-eol-date": "11-30-2023",
            "rds-standard-eos-date": "02-29-2024",
            "rds-extended-support-yr1-stat-date": "04-01-2024",
            "rds-extended-support-yr3-stat-date": "04-01-2026",
            "rds-extended-eos-date": "03-31-2027",
            "minor-versions-eligible-extended-support": ["postgres-aurora-11.9", "postgres-aurora-11.21"]
    
        }
    }

RDS_EXTENDED_SUPPORT_VERSION = {
        "mysql-5.7":{
            "community-eol-date": "10-31-2023",
            "rds-standard-eos-date": "02-29-2024",
            "rds-extended-support-yr1-stat-date": "03-01-2024",
            "rds-extended-support-yr3-stat-date": "03-01-2026",
            "rds-extended-eos-date": "02-28-2027",
        },
        "postgres-11": {
            "community-eol-date": "11-09-2023",
            "rds-standard-eos-date": "02-29-2024",
            "rds-extended-support-yr1-stat-date": "04-01-2024",
            "rds-extended-support-yr3-stat-date": "04-01-2026",
            "rds-extended-eos-date": "03-31-2027",
        }
    }

aurora_provisioned_price_map = {}
aurora_serverless_v2_price_map = {}
db_engine_price_map = {}

def get_rds_regions(regions_file_path):
    LOGGER.debug("Extracting a list of AWS Regions for RDS")
    url = "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.RegionsAndAvailabilityZones.html"
    try:
        response = requests.get(url, timeout=10)    # 10 seconds
        response.raise_for_status()
    except Exception as e:
        LOGGER.error(f'Failed to get a http response from {url} to get AWS regions, script exiting...')
        raise
    soup = BeautifulSoup(response.content, "html.parser")

    regions_section = soup.find("h3", {"id": "Concepts.RegionsAndAvailabilityZones.Availability"})
    LOGGER.debug(f'Regions section: {regions_section}')

    regions_section_tables = regions_section.find_all_next("table")
    LOGGER.debug(f'Regions section tables: {regions_section_tables}')

    # table = soup.find("table", {"id": "w1178aab5c45c29b7b9"})
    table = regions_section_tables[0]
    rows = table.find_all("tr")[1:]

    regions_map = {}
    #populate regions_map with all RDS supported regions
    for row in rows:
        cols = row.find_all("td")
        region_name = cols[0].text.strip()
        region_id = cols[1].text.strip()
        regions_map[region_id] = region_name

    if not regions_file_path:   # user has not provided a regions file
        LOGGER.debug(f'Regions map: {regions_map}')
        LOGGER.debug(f'Number of regions: {len(regions_map)}')
        return regions_map
    else:   # user has provided a regions file, read the regions from the file and validate it
        user_regions_list = read_regions_from_file(regions_file_path)

        for r in user_regions_list:
            if r not in regions_map:
                LOGGER.error("User provided regions file has invalid regions. Please fix the file, making sure you enter AWS regions ids separated by newline. Please see README for instructions on how to generate a sample Regions file")
                raise ValidationException('Invalid input: regions has invalid regions. Please fix the file & try again.')
        
        # return map with only matching entries
        regions_map = {k:v for k,v in regions_map.items() if k in user_regions_list}

        LOGGER.debug(f'Filtered Regions map: {regions_map}')
        LOGGER.debug(f'Number of regions: {len(regions_map)}')
        return regions_map    

"""
Get a mapping of db instance types to the vCPUs used
For eg: db.m6i.large = 2 vCPUs
"""
def get_rds_instance_mapping():
    LOGGER.debug("Extracting the vCPU to RDS Instance size mapping")
    url = "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.DBInstanceClass.html"
    try:    
        response = requests.get(url, timeout=10)    # 10 seconds
        response.raise_for_status()
    except Exception as e:
        LOGGER.error(f'Failed to get a http response from {url} to get RDS instance mappings, script exiting...')
        raise
    soup = BeautifulSoup(response.content, "html.parser")

    mappings_section = soup.find("h2", {"id": "Concepts.DBInstanceClass.Summary"})
    LOGGER.debug(f'Mappings section: {mappings_section}')

    mappings_section_tables = mappings_section.find_all_next("table")
    LOGGER.debug("mappings_section_tables: {}".format(mappings_section_tables))

    #table = soup.find("table", {"id": "w1178aab5c37c39c17"})
    
    db_map = {}

    for table in mappings_section_tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols)>1:
                db_class = (cols[0].text.strip()).strip('*')
                default_vcpus = cols[1].text.strip()
                db_map[db_class] = default_vcpus

    LOGGER.debug(f'DB Instance Mapping: {db_map}')
    return db_map

def get_rds_extended_support_pricing(db_engine):
    global aurora_provisioned_price_map
    global aurora_serverless_v2_price_map
    global db_engine_price_map

    if db_engine == 'aurora':
        if len(aurora_provisioned_price_map) >0:
            LOGGER.debug("Returning cached prices for Aurora Extended Support")
            return aurora_provisioned_price_map, aurora_serverless_v2_price_map
        else:
            LOGGER.debug("No cached prices found for Aurora Extended Support, getting prices from AWS Pricing page")
    else:
        if len(db_engine_price_map) > 0:
            LOGGER.debug("Returning cached prices for RDS Extended Support")
            return db_engine_price_map, "N/A"
        else:
            LOGGER.debug("No cached prices found for RDS Extended Support, getting prices from AWS Pricing page")
    
    api_filters = {
        'mysql': {'databaseEngine': 'MySQL', 'engineMajorVersion': '5.7'},
        'postgres': {'databaseEngine': 'PostgreSQL', 'engineMajorVersion': '11'},
        'aurora': {'databaseEngine': 'Aurora PostgreSQL', 'engineMajorVersion': '11'}
    }

    # Filter for AWS Price List Query API
    FILTER='[{{"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "{e}"}},'\
            '{{"Type": "TERM_MATCH", "Field": "engineMajorVersion", "Value": "{v}"}},'\
            '{{"Type": "TERM_MATCH","Field": "extendedSupportPricingYear","Value": "{y}"}}]'

    def get_price_map(db_engine):
        price_map = {}
        extended_support_pricing = boto3.client('pricing', region_name='us-east-1')

        engine = api_filters[db_engine]['databaseEngine']
        major_version = api_filters[db_engine]['engineMajorVersion']
        year_options = {
            'yr_1_2_price': 'Year 1, Year 2', 
            'yr_3_price': 'Year 3'
        }

        for year_code, year_string in year_options.items():
            f = FILTER.format(e=engine, v=major_version, y=year_string)
            LOGGER.debug(f'AWS Pricing API filter: {f} for engine {db_engine}')

            response = extended_support_pricing.get_products(
                            ServiceCode='AmazonRDS',
                            FormatVersion='aws_v1',
                            Filters=json.loads(f) 
                        )
            if 'PriceList' in response and len(response['PriceList']) > 0:
                price_list = response['PriceList']
            else:
                LOGGER.error("Invalid Arguments for databaseEngine: {}, engineMajorVersion: {} or ExtendedSupportPricingYear: {}".format(engine, major_version, year_string))
                raise Exception('Invalid Arguments for DB Engine, EngineVersion or ExtendedSupportPricingYear')
        
            LOGGER.debug(f'extended support pricing response: {price_list}')
            for obj in price_list:
                sku = json.loads(obj)
                region = sku['product']['attributes']['location']
                if region not in price_map:
                    price_map[region] = {}
                ''' Since the pricing API returns a dict with dynamically generated keys which are not pre-known, 
                in order to access the 'pricePerUnit' child attributes, we need to convert the dict into list to 
                access the dict's key elements at known positions in the list.
                For eg, the following is the returned response from pricing API: 
                    "terms": {
                        "OnDemand": {
                            "YZBJ7XT2D98GGDZH.99YE2YK9UR": {                    <<<--- dynamic not pre-known key
                                "priceDimensions": {
                                    "YZBJ7XT2D98GGDZH.99YE2YK9UR.Q7UJUT2CE6": { <<<--- dynamic, not pre-known key
                                        "pricePerUnit": {
                                            "USD": "1.9480000000"
                                        }
                                    }
                                },
                            }
                        }
                    }
                then id1 in below code points to the dict key `YZBJ7XT2D98GGDZH.99YE2YK9UR` and id2 points to the dict key `YZBJ7XT2D98GGDZH.99YE2YK9UR.Q7UJUT2CE6`
                '''
                od = sku['terms']['OnDemand']
                id1 = list(od)[0]
                id2 = list(od[id1]['priceDimensions'])[0]
                if 'USD' in od[id1]['priceDimensions'][id2]['pricePerUnit']:
                    extended_support_price = od[id1]['priceDimensions'][id2]['pricePerUnit']['USD']
                else:
                    continue

                price_map[region].update({year_code: float(extended_support_price)})
            
        return price_map

    LOGGER.info(f'Extracting RDS extended support pricing for engine {db_engine} using Pricing API')
    db_engine_price_map = get_price_map(db_engine)
    LOGGER.debug(f'db engine price map: {db_engine_price_map}')
    return db_engine_price_map, "N/A"


def is_extended_support_eligible(rds_instance):
    if rds_instance['Engine'] in ['aurora-mysql']: 
        if ("mysql_aurora.2.11" in rds_instance['EngineVersion']) or ("mysql_aurora.2.12" in rds_instance['EngineVersion']):
            return True
    
    if rds_instance['Engine'] in ['aurora-postgresql'] and rds_instance['EngineVersion'] in ["11.9", "11.21"]:
            return True
    
    if rds_instance['Engine'] in ['mysql'] and "5.7" in rds_instance['EngineVersion']:
        return True
    
    if rds_instance['Engine'] in ['postgres'] and "11" in rds_instance['EngineVersion']:
        return True
    
    return False


def main():
    #get_rds_extended_support_pricing('mysql')
    get_rds_regions()
    #get_rds_instance_mapping()

if __name__ == '__main__':
    main()