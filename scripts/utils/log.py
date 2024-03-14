# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import logging
import sys


def get_logger(name):
    """
    Setup and return a logger that writes to stdout with logging level set to INFO
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(threadName)s - %(message)s')
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger