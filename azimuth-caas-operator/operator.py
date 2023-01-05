import logging

import kopf

LOG = logging.getLogger(__name__)

@kopf.on.startup()
def startup(**kwargs):
    LOG.info("started!")


@kopf.on.cleanup()
def cleanup(**kwargs):
    LOG.info("cleaned up!")
