# themis-lambda

## Description

themis-lambda is an AWS lambda function that scans an auto scaling group's member instances and then sets instance protection on the busy instances and removes instance protection from the idle instances.

At `$JOB`, we've got services that have long-running (tens of minutes, sometimes even hours) work units. It is extremely frustrating to have the autoscaler do a scale-down event and have it terminate one of the busy instances instead of one that is idle. Fortunately, AWS allows you to set instance protection so that the autoscaler which instances should not be terminated.

For reasons, we don't want to grant the IAM role that our autoscaling instances run under the power to change their own instance protection.

## Prerequisites

### Runtime

Your instances must run an http server on a port, and have a standard URL that can be scraped to determine the instance's busy status.

### Building

I developed themis using Nick Ficano's [python-lambda](https://github.com/nficano/python-lambda) framework. Follow the directions there to get it running, then you can `lambda deploy` to upload it.

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

