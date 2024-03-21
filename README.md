# rds-extended-support-cost-estimator-script

## RDS Extended Support Cost Estimator Script

In September 2023, we [announced Amazon RDS Extended Support](https://aws.amazon.com/about-aws/whats-new/2023/09/amazon-aurora-rds-extended-support-mysql-postgresql-databases/), which allows you to continue running your database on a major engine version past its RDS end of standard support date on Amazon Aurora or Amazon RDS at an additional cost. 

These scripts can be used to help estimate the cost of RDS Extended Support for RDS instances & clusters in your AWS account and organization.

These scripts should be run from the payer account of your organization to identify the RDS clusters in your organization that will be impacted by the extended support and the estimated additional cost for the following DB engines:

* Amazon RDS for PostgreSQL - version 11
* Amazon RDS for MySQL - version 5.7
* Amazon Aurora - versions mysql_aurora-2.11, mysql_aurora-2.12, postgres-aurora-11.9, postgres-aurora-11.21


Note:

* Amazon RDS Extended Support for Aurora MySQL 5.7 starts on November 1, 2024, but will not be charged until December 1, 2024. 
* Amazon RDS Extended Support for Aurora PostgreSQL 11 starts on March 1, 2024, but will not be charged until April 1, 2024. 
* RDS Extended Support for PostgreSQL 11 starts on March 1, 2024, but will not be charged until April 1, 2024. 

Per the Amazon [RDS Aurora pricing page](https://aws.amazon.com/rds/aurora/pricing/#Amazon_RDS_Extended_Support_costs)
Amazon RDS Extended Support year 3 pricing is only available for Amazon Aurora PostgreSQL-Compatible Edition.
Extended Support for Amazon Aurora MySQL compatible engine is charged at Year 1 prices for the entire duration 
of Extended Support for the respective major version. The script factors in this change in the pricing estimation.

The scripts will create a CSV file with all the RDS instances that will be impacted by extended support across all affected RDS clusters in your organization.

These scripts provide the following benefits:
* Streamlined identification: Quickly identify all RDS instances enabled for RDS Extended Support across your entire AWS organization and all regions in one go.
* Enhanced visibility and cost awareness: Easily calculate the total yearly cost of extended support for eligible instances, gaining insight into cost implications and enabling informed decision-making to optimize expenses, maximize savings, and ensure timely action and compliance.
* Time-saving automation: Eliminate manual effort by automating the process of listing RDS instances, saving valuable time for your team. Run the script for a single account, a list of accounts or for the entire organization.
* Proactive management: Stay ahead of extended support deadlines by proactively identifying instances requiring attention, minimizing potential disruptions.

## Prerequisites

1. Download and install [Python 3](https://www.python.org/downloads/).

2. Ensure that you have an IAM principal in your payer/management account that has at least the following IAM permissions:
> NOTE: The script does NOT create these roles/policies in your management account. It is assumed that a user with these permissions already granted to them will run the steps listed here.

```
"organizations:ListAccounts",
"organizations:DescribeOrganization",

"sts:AssumeRole",

"cloudformation:CreateStackSet",
"cloudformation:UpdateStackSet",
"cloudformation:DeleteStackSet",
"cloudformation:ListStackSetOperationResults",
"cloudformation:ListStackInstances",
"cloudformation:StopStackSetOperation"
"cloudformation:CreateStackInstances",
"cloudformation:UpdateStackInstances",
"cloudformation:DeleteStackInstances",

"rds:DescribeDBEngineVersions",
"rds:DescribeDBInstances",
"rds:DescribeDBClusters"
```
These are the minimum permissions needed to create and execute the cloudformation stack/stack-set across the management & all linked accounts in your AWS Organizations. In addition, this also includes the permissions needed to read RDS instance details used by the script. You will be using this IAM principal to configure AWS credentials before running the scripts.

## Step 1: Clone the repo

1. On your laptop, clone the project in a local directory
    ```
    git clone https://github.com/aws-samples/rds-extended-support-cost-estimator.git
    ```

2. Navigate into the project
    ```
    cd rds-extended-support-cost-estimator
    ```

## Step 2: Create the CloudFormation StackSets

Follow this procedure to create CloudFormation StackSets. The stack set creates an IAM role named *RDSExtendedSupportCostEstimatorRole*
across all member accounts of your organization. This IAM role will be assumed by the payer account during the script execution
to query affected RDS instances in the member accounts.

**Note**:
You only need to complete this step once from the management account (payer account).

**Important**:
Running a stack set does not execute the stack on the management account itself, it will only run on all child accounts. 
To run on management account, in case there are RDS instances in it, run it as a standalone cloudformation stack first, and then run a stack set for the Organization.


**To create the CloudFormation StackSets**

1. Sign in to the AWS Management Console of the payer/management account as a user assigned the minimum IAM permissions as mentioned in Prerequisites step #2 above.
2. In the CloudFormation console, select StackSets in the left navigation panel and create a stack set with the template file that you downloaded. Provide the Management Account ID as the input parameter when asked on the console.
3. For the template, use the [rds_extended_support_cost_estimator_role.yaml](rds_extended_support_cost_estimator/cfn_template/rds_extended_support_cost_estimator_role.yaml) template file in the cfn_template directory of the cloned repo.
4. For Region, select any one region only (eg us-east-1). You only need to select a single region as the cloudformation template creates a single IAM role, which is a global service.

For more information, see [Creating a stack set on the AWS CloudFormation console](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-getting-started-create.html)
in the AWS CloudFormation User Guide.

After CloudFormation creates the stack set, each member account in your organization has *RDSExtendedSupportCostEstimatorRole* IAM role.
The IAM role contains the following permissions:
```
"rds:DescribeDBEngineVersions",
"rds:DescribeDBInstances",
"rds:DescribeDBClusters"
```

## Step 3: Set up the environment

Execute the following steps from the directory that was created after cloning the project. 

1. [**ONLY applicable to Debian/Ubuntu systems**] Install python3-venv

   This command should only be run if you are using Debian/Ubuntu systems. For all other systems, skip this and
   move to 4.
   ```
   sudo apt install -y python3-venv
   ```

2. Setup virtualenv
    ```
    python3 -m venv venv
    ```

3. Activate virtualenv
    ```
    source venv/bin/activate
    ```

4. Install dependencies
    ```
    pip install -r requirements.txt
    ```

5. Navigate to directory containing the scripts
    ```
    cd scripts/
    ```

6. Configure the credentials using AWS CLI. You can read more about how to do this [here](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html#interactive-configuration).
   Credentials can be configured in multiple ways. Regardless of the method that you choose, you must have both **AWS credentials**
   and an **AWS Region** set before running the scripts. The simplest way is to do this in an interactive manner using AWS CLI
   and running `aws configure` command to set up your credentials and default region. Follow the prompts, and it will generate
   configuration files in the correct locations for you.

**Note:**
Specifying incorrect region can cause errors during script execution. For e.g. when running the script in China regions,
if the region is set to *us-east-1* you will see errors like - `The security token included in the request is invalid`.
For China regions, the region value should be either *cn-north-1* or *cn-northwest-1*.


## Step 4: Identify the affected RDS instances

To identify affected RDS instances run the `find_rds_extended_support_instances.py` script

The script supports the following arguments:
```
$ python3 find_rds_extended_support_instances.py -h

usage: find_rds_extended_support_instances.py [-h] [-a ACCOUNTS | --accounts-file ACCOUNTS_FILE | --all] [--regions-file REGIONS_FILE] [--exclude-accounts EXCLUDE_ACCOUNTS] [--generate-accounts-file] [--generate-regions-file]

optional arguments:
  -h, --help            show this help message and exit
  -a ACCOUNTS, --accounts ACCOUNTS
                        comma separated list of AWS account IDs
  --accounts-file ACCOUNTS_FILE
                        Absolute path of the CSV file containing AWS account IDs
  --all                 runs script for the entire AWS Organization
  --regions-file REGIONS_FILE
                        Absolute path of the CSV file containing specific AWS regions to run the script against
  --exclude-accounts EXCLUDE_ACCOUNTS
                        comma separated list of AWS account IDs to be excluded, only applies when --all flag is used
  --generate-accounts-file
                        Creates a `accounts.csv` CSV file containing all AWS accounts in the AWS Organization
  --generate-regions-file
                        Creates a `regions.csv` CSV file containing all AWS regions
``` 

The details about using these input parameters are below:

* --all – Scans all member accounts in your organization.

```
python find_rds_extended_support_instances.py --all
```

* --accounts – Scans a subset of member accounts in your organization.

```
python find_rds_extended_support_instances.py --accounts 111122223333,444455556666,777788889999
```

* --accounts-file – Absolute path to the CSV file containing a subset of member accounts in your organization that needs
  to be scanned. The CSV file should have no headers and contain 12 digit AWS Account IDs in the first column of the file.

```
python find_rds_extended_support_instances.py --accounts-file /path/to/accounts_file.csv
```

* --exclude-accounts – Excludes specific member accounts in your organization. Can only be used with --all

```
python find_rds_extended_support_instances.py --all --exclude-accounts 111111111111,222222222222,333333333333
```

* If no argument is provided, script runs for the current account (payer account)

```
python find_rds_extended_support_instances.py
```

* --generate-accounts-file - Creates a `accounts.csv` CSV file in the current directory containing all AWS accounts in the AWS Organization. You can then edit/remove the accounts that you do not need from the CSV and use this file as a script input. Note: using this option will ignore all other script parameters and exit after generating the file.

```
python find_rds_extended_support_instances.py --generate-accounts-file
python find_rds_extended_support_instances.py --accounts-file /path/to/accounts.csv
```

* --generate-regions-file - Creates a `regions.csv` CSV file in the current directory containing all AWS regions. You can then edit/remove the regions that you do not need from the CSV and use this file as a script input. Note: using this option will ignore all other script parameters and exit after generating the file.

```
python find_rds_extended_support_instances.py --generate-regions-file
python find_rds_extended_support_instances.py --all --regions-file /path/to/regions.csv
```

After you run the script, it creates a CSV file in the <pwd>/output/rds_extended_support_instances_<*Timestamp*> format in the `output` directory.

## Output
The script creates a folder called `output/` in the same directory where the script runs from on first run. Subsequently, it uses the `output/` folder to save the results.

The final output of the script is a csv called `./output/rds_extended_support_instances-<timestamp>.csv` in the same directory where the script is run from. The headers of the csv are: 
```
DBInstanceIdentifier : DB Instance name or identifier
DBInstanceClass      : DB Instance Class, eg `db.t2.micro`
Engine               : DB Engine, eg `postgres`
EngineVersion        : DB Engine Version, eg `11.19`
DBInstanceStatus     : DB Instance Status, eg `available`
MultiAZ              : Indicates if this is a Multi-AZ instance
DBInstanceArn        : The RDS ARN for the DB Instance
AccountId            : The AWS account ID
Region               : The Region in which the DB instance is in, eg `us-east-1`
RegionName           : The full AWS region name, eg `US East (N. Virginia)`
vCPUs per instance   : The number of vCPUs used by the DB Instance class
Total vCPUs (if MultiAZ) : The total number of vCPUs, if Multi-AZ is enabled.
Year 1 Price         : The yearly price for RDS Extended Support for Year 1
Year 2 Price         : The yearly price for RDS Extended Support for Year 2
Year 3 Price         : The yearly price for RDS Extended Support for Year 3
```


## Cleanup
If you do not need to run the script again in future, you can simply delete the project folder from your laptop.

To remove the IAM role that was created using the CloudFormation Stack/StackSets, follow the steps to remove the stacks and then delete the stack set, as per the [AWS Documentation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-getting-started.html). This will delete the IAM role from your linked accounts. If the cloudformation stack set was deployed for the organization, then you will need the AWS Organizations OU-ID when deleting stack from the stack set. You can obtain it from the AWS Organizations console. 

If the Cloudformation stack fails to delete for any reason, please perform a manual cleanup of the *RDSExtendedSupportCostEstimatorRole* IAM role from the accounts where the stack failed to delete.

**NOTE:** Make sure you [Delete stack instances from your stack set](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stackinstances-delete.html) before trying to [Delete the stack set](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-delete.html) itself. 


## Troubleshooting

### IAM role “RDSExtendedSupportCostEstimatorRole” not created in all member accounts of an AWS Organization

This issue mostly occurs when you create a stack instead of a **“stack set”** in [step 2](README.md#step-2-create-the-cloudformation-stack-set)
of this procedure. If you create a stack, this only creates the required IAM role in the management account.
You must create a CloudFormation “stack set” in the management account of your AWS organization. Using a stack set
ensures that the required IAM role is created for all member accounts in the organization. Please see this AWS Documentation link to get started with [AWS CloudFormation Stack Sets](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stacksets-getting-started.html)

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
