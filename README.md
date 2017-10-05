# themis-lambda

## Description

themis-lambda is an AWS lambda function that scans an auto scaling group's member instances and then sets instance protection on the busy instances and removes instance protection from the idle instances.

At `$JOB`, we've got services that have long-running (tens of minutes, sometimes even hours) work units. It is extremely frustrating to have the autoscaler do a scale-down event and have it terminate one of the busy instances instead of one that is idle. Fortunately, AWS allows you to set instance protection so that the autoscaler which instances should not be terminated.

For reasons, we don't want to grant the IAM role that our autoscaling instances run under the power to change their own instance protection.

## Setup

### Runtime

#### ASG Instances

Your instances must run an http server on a port, and have a standard URL that can be scraped to determine the instance's busy status.

### Lambda

First, create an IAM policy (all-autoscaling-rw) with the following permissions:

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "autoscaling:*",
            "Resource": "*"
        }
    ]
}
```
You'll find a copy of the policy in the policies directory.

Then, create an IAM role for your lambda with the following policies attached:

* AmazonEC2ReadOnlyAccess
* AWSLambdaBasicExecutionRole
* AWSLambdaVPCAccessExecutionRole
* all-autoscaling-rw

Set the trust relationships so that **lambda.amazonaws.com** and **edgelambda.amazonaws.com** can assume this role.

### Building

I developed themis using Nick Ficano's [python-lambda](https://github.com/nficano/python-lambda) framework. Follow the directions there to get it running, then:

1. `lambda build` to create a zip of themis
2. Upload the zipfile to S3
3. Create a new lambda and upload from S3

## How it works

Themis is passed an event with an asgID definition. 

```
{
  "asgName": "Electric-Ziggurat",
  "region": "us-tirefire-1"
  "metricsPort": 9000,
  "busyURL": "work_status",
  "busyValue": "BUSY",
  "idleValue": "IDLE",
  "dryRun": false
}

```

It will then determine what instances are in that ASG, probe each instance's metrics port via HTTP (on its private IP address), and check the **busyURL**. It will then enable instance protection on all the instances that return **busyValue**, and remove instance protection from all the instances that return **idleValue**.

