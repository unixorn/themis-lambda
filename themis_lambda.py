#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

'''
themis-lambda is a tool to scan autoscaling groups and determine which
instances are busy and which are not, then apply instance protection to
the busy instances so they won't be killed during scale-down events.

Sample Trigger Event
{
  "asgName": "Electric-Horse-Ziggurat",
  "metricsPort": 9000,
  "busyURL": "/work_status",
  "busyValue": "BUSY",
  "idleValue": "IDLE"
}
'''

import logging
import sys
import urllib2

import boto3
from logrus.utils import getCustomLogger, squashDicts

# this is a pointer to the module object instance itself. We'll attach
# a logger to it later.
this = sys.modules[__name__]


def getASGInstances(asgID=None, client=None, NextToken=None, MaxRecords=10):
  '''
  Get the members of an autoscaling group

  :param str asgID: What Autoscaling group to list
  :param int MaxRecords: How many instances to look at at a time
  :param boto3client client: boto3 autoscaling client
  :param boto3 pagination token NextToken: token for the next page of results
  '''
  assert isinstance(asgID, basestring), ("asgID must be a string but is %r." % asgID)

  response = None
  if NextToken:
    response = client.describe_auto_scaling_instances(MaxRecords=MaxRecords, NextToken=NextToken)
  else:
    response = client.describe_auto_scaling_instances(MaxRecords=MaxRecords)

  for i in response['AutoScalingInstances']:
    if i['AutoScalingGroupName'] == asgID:
      yield i['InstanceId']

  if 'NextToken' in response:
    for i in getASGInstances(client=client, asgID=asgID, NextToken=response['NextToken']):
      yield i


def setASGInstanceProtection(asgName=None, client=None, instances=None, protected=True, dryRun=False):
  '''
  Set instance protection for instances in instanceList so that they are
  not terminated during a scale-down event in the ASG

  :param str asgName: Autoscaling group to affect
  :param list instances: list of instance IDs to change protection status for
  :param bool protected: What to set the instance protection to
  '''
  assert isinstance(asgName, basestring), ("asgName must be a basestring but is %r." % asgName)
  assert isinstance(dryRun, bool), ("dryRun must be a bool but is %r." % dryRun)
  assert isinstance(instances, list), ("instances must be a list but is %r." % instances)
  assert isinstance(protected, bool), ("protected must be a bool but is %r." % protected)

  this.logger.info('Setting %s instance protection to %s', instances, protected)
  if dryRun:
    this.logger.info('dry run - not altering instance protection')
    return None
  else:
    response = client.set_instance_protection(InstanceIds=instances,
                                              AutoScalingGroupName=asgName,
                                              ProtectedFromScaleIn=protected)
  return response


def getPrivateIP(client=None, instanceID=None):
  '''
  Return the private IP of an instance
  '''
  assert isinstance(instanceID, basestring), ("instanceID must be a basestring but is %r." % instanceID)

  instanceData = client.describe_instances(InstanceIds=[instanceID])
  return instanceData['Reservations'][0]['Instances'][0]['PrivateIpAddress']


def getInstanceWorkStatuses(client=None,
                            instances=None,
                            busyURL='/work_status',
                            metricsPort=9000,
                            busyValue='BUSY',
                            idleValue='IDLE'):
  '''
  Check instance work status
  '''
  assert isinstance(busyURL, basestring), ("busyURL must be a basestring but is %r." % busyURL)
  assert isinstance(busyValue, basestring), ("busyValue must be a basestring but is %r." % busyValue)
  assert isinstance(idleValue, basestring), ("idleValue must be a basestring but is %r." % idleValue)
  assert isinstance(instances, list), ("instances must be a list but is %r." % instances)
  assert isinstance(metricsPort, int), ("metricsPort must be an int but is %r." % metricsPort)

  statuses = {}
  statuses['busy'] = {}
  statuses['idle'] = {}
  statuses['error'] = {}
  this.logger.info('Checking instances %s', list(instances))
  for i in instances:
    this.logger.info('Checking %s', i)
    privateIP = getPrivateIP(client=client, instanceID=i)
    this.logger.info('%s has IP %s, checking busy status', i, privateIP)
    try:
      statusURL = "http://%s:%s/%s" % (privateIP, metricsPort, busyURL)
      this.logger.debug('Checking %s for instance status', statusURL)
      probe = urllib2.urlopen(statusURL)
      workStatus = probe.read().lower().strip()
    except urllib2.URLError as e:
      workStatus = e.reason
      this.logger.warning(workStatus)
    this.logger.info('status: %s', workStatus)
    if workStatus == busyValue.lower().strip():
      this.logger.info('adding %s to busy list', i)
      statuses['busy'][i] = privateIP
    elif workStatus == idleValue.lower().strip():
      this.logger.info('adding %s to idle list', i)
      statuses['idle'][i] = privateIP
    else:
      this.logger.warning('%s is not reporting work state', i)
      statuses['error'][i] = privateIP
  return statuses


def processASG(asgName=None,
               region=None,
               busyURL=None,
               metricsPort=9000,
               busyValue='BUSY',
               idleValue='IDLE',
               dryRun=False):
  '''
  Process an ASG and return a dict describing the busy statuses of the
  instances in the ASG.

  :param str asgName: Auto Scaling Group to process
  :param str busyURL: What url to probe on the instances in the ASG
  :param int metricsPort: What port for the http server reporting the busy status
  :param str busyValue: What busy instances will return. Default 'BUSY'
  :param str idleValue: What idle instances will return. Default 'IDLE'
  :param bool dryRun: whether or not to change instances instance protection
  '''
  assert isinstance(asgName, basestring), ("asgName must be a basestring but is %r." % asgName)
  assert isinstance(busyURL, basestring), ("busyURL must be a basestring but is %r." % busyURL)
  assert isinstance(busyValue, basestring), ("busyValue must be a basestring but is %r." % busyValue)
  assert isinstance(dryRun, bool), ("dryRun must be a bool but is %r." % dryRun)
  assert isinstance(idleValue, basestring), ("idleValue must be a basestring but is %r." % idleValue)
  assert isinstance(metricsPort, int), ("metricsPort must be a int but is %r." % metricsPort)
  assert isinstance(region, basestring), ("region must be a basestring but is %r." % region)

  if dryRun:
    this.logger.warning('Activating dry-run mode')

  # Set up boto3 connections
  asgClient = boto3.client('autoscaling', region_name=region)
  ec2client = boto3.client('ec2', region_name=region)

  instances = list(getASGInstances(asgID=asgName, client=asgClient, MaxRecords=50))
  this.logger.info('ASG %s members: %s', asgName, instances)

  this.logger.info('Checking which members are busy...')
  asgInstanceStatuses = getInstanceWorkStatuses(client=ec2client,
                                                busyURL=busyURL,
                                                busyValue=busyValue,
                                                idleValue=idleValue,
                                                metricsPort=metricsPort,
                                                instances=list(instances))
  this.logger.info('Statuses: %s', asgInstanceStatuses)

  # if cliArgs.unprotectAllInstances:
  #   # Unset instance protection
  #   setASGInstanceProtection(client=asgClient,
  #                            asgID=cliArgs.autoScalingGroup,
  #                            instances=instances,
  #                            dryRun=cliArgs.dryRun,
  #                            protected=False)
  # else:
  this.logger.info('Applying instance protection')
  if len(asgInstanceStatuses['busy'].keys()) > 0:
    setASGInstanceProtection(client=asgClient,
                             asgName=asgName,
                             instances=asgInstanceStatuses['busy'].keys(),
                             dryRun=dryRun,
                             protected=True)
  else:
    this.logger.info('No instances reporting busy status')

  if len(asgInstanceStatuses['idle'].keys()) > 0:
    setASGInstanceProtection(client=asgClient,
                             asgName=asgName,
                             instances=asgInstanceStatuses['idle'].keys(),
                             dryRun=dryRun,
                             protected=False)
  else:
    this.logger.info('No instances reporting idle status')

  if len(asgInstanceStatuses['error'].keys()) > 0:
    this.logger.warning('The following instances did not report a status and are not going to be touched:')
    this.logger.warning(asgInstanceStatuses['error'])
  else:
    this.logger.info('No problems checking instance idle status')
  return asgInstanceStatuses


def handler(event, context):
  '''
  Handle incoming events from AWS
  '''
  asgName = event.get('asgName')
  busyURL = event.get('busyURL')
  busyValue = event.get('busyValue')
  idleValue = event.get('idleValue')
  logLevel = event.get('logLevel')
  metricsPort = event.get('metricsPort')
  region = event.get('region')
  # debug = event.get('DEBUG')
  dryRun = event.get('dryRun')

  # Sanity check and default setting
  if not asgName:
    raise ValueError, 'You must specify an asgName'
  else:
    print 'asgName: ' + asgName

  # Set up logging
  if not logLevel:
    logLevel = 'INFO'

  logLevel = logLevel.upper()

  logname = "themis-lambda-%s" % asgName
  this.logger = getCustomLogger(name=logname, logLevel=logLevel)
  this.logger.debug('Setting log level to %s', logLevel)
  this.logger.info('Processing %s', asgName)

  if not metricsPort:
    # Use the standard Apgar port
    metricsPort = 9000
    this.logger.info('Using default metricsPort %s', metricsPort)

  if not busyURL:
    busyURL = '/work_status'
    this.logger.info('Using default busyURL %s', busyURL)

  if not busyValue:
    busyValue = 'BUSY'
    this.logger.info('Using default busyValue %s', busyValue)

  if not idleValue:
    idleValue = 'IDLE'
    this.logger.info('Using default idleValue %s', idleValue)

  if not region:
    region = 'us-west-2'
    this.logger.info('Using default region %s', region)

  this.logger.debug('asgName: %s', asgName)
  this.logger.debug('region: %s', region)
  this.logger.debug('busyURL: %s', busyURL)
  this.logger.debug('busyValue: %s', busyValue)
  this.logger.debug('idleValue: %s', idleValue)
  this.logger.debug('metricsPort: %s', metricsPort)
  return processASG(asgName=asgName,
                    region=region,
                    busyURL=busyURL,
                    metricsPort=metricsPort,
                    busyValue=busyValue,
                    idleValue=idleValue,
                    dryRun=dryRun)
  # return asgName
