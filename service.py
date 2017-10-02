# -*- coding: utf-8 -*-

def handler(event, context):
    # Your code goes here!
    asgID = event.get('asgID')
    return asgID
