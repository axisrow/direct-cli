"""
Command handlers for Direct CLI
"""

from .campaigns import campaigns
from .adgroups import adgroups
from .ads import ads
from .keywords import keywords
from .keywordbids import keywordbids
from .bids import bids
from .bidmodifiers import bidmodifiers
from .audiencetargets import audiencetargets
from .retargeting import retargeting
from .creatives import creatives
from .adimages import adimages
from .adextensions import adextensions
from .sitelinks import sitelinks
from .vcards import vcards
from .leads import leads
from .clients import clients
from .agencyclients import agencyclients
from .dictionaries import dictionaries
from .changes import changes
from .reports import reports
from .turbopages import turbopages
from .negativekeywordsharedsets import negativekeywordsharedsets
from .feeds import feeds
from .smartadtargets import smartadtargets
from .businesses import businesses
from .keywordsresearch import keywordsresearch
from .dynamicads import dynamicads

__all__ = [
    "campaigns",
    "adgroups",
    "ads",
    "keywords",
    "keywordbids",
    "bids",
    "bidmodifiers",
    "audiencetargets",
    "retargeting",
    "creatives",
    "adimages",
    "adextensions",
    "sitelinks",
    "vcards",
    "leads",
    "clients",
    "agencyclients",
    "dictionaries",
    "changes",
    "reports",
    "turbopages",
    "negativekeywordsharedsets",
    "feeds",
    "smartadtargets",
    "businesses",
    "keywordsresearch",
    "dynamicads",
]
