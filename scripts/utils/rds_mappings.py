# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

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
    
    #table = soup.find("table", {"id": "w1178aab5c37c39c17"})
    table = mappings_section_tables[0]
    rows = table.find_all("tr")
    db_map = {}
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
    
    urls = {
        'mysql': 'https://aws.amazon.com/rds/mysql/pricing/',
        'postgres': 'https://aws.amazon.com/rds/postgresql/pricing/',
        'aurora': 'https://aws.amazon.com/rds/aurora/pricing'
    }

    def get_price_map(table):
        rows = table.find_all("tr")[1:]
        price_map = {}
        for row in rows:
            cols = row.find_all("td")
            #print(cols)
            region = cols[0].text.strip()
            yr_1_2_price = float((cols[1].text.strip()).strip('$'))
            yr_3_price = float((cols[2].text.strip()).strip('$'))
            price_map[region] = {
                "yr_1_2_price": yr_1_2_price,
                "yr_3_price": yr_3_price
            }
        return price_map

    LOGGER.info(f'Extracting RDS extended support priciing for engine {db_engine} from {urls[db_engine]}')
    try:
        response = requests.get(urls[db_engine], timeout=10)    # 10 seconds
        response.raise_for_status()
    except Exception as e:
        LOGGER.error(f'Failed to get a http response from {urls[db_engine]} to get RDS extended support pricing, script exiting...')
        raise
    soup = BeautifulSoup(response.content, "html.parser")

    extended_support_section = soup.find("h2", {"id": "Amazon_RDS_Extended_Support_costs"})
    LOGGER.debug(f'Extended support section: {extended_support_section}')

    extended_support_section_tables = extended_support_section.find_all_next("table")

    if db_engine == 'aurora':
        aurora_provisioned = extended_support_section_tables[0]
        aurora_serverless_v2 = extended_support_section_tables[1]

        aurora_provisioned_price_map = get_price_map(aurora_provisioned)
        aurora_serverless_v2_price_map = get_price_map(aurora_serverless_v2)
        LOGGER.debug(f'aurora provisioned price map: {aurora_provisioned_price_map}')
        LOGGER.debug(f'aurora serverless v2 price map: {aurora_serverless_v2_price_map}')
        return aurora_provisioned_price_map, aurora_serverless_v2_price_map
    else:
        db_engine_provisioned = extended_support_section_tables[0]
        db_engine_price_map = get_price_map(db_engine_provisioned)
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