# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Contains functions for building and sending build status to a pub/sub topic.
See api.py docstring for more information.
"""

from PB.recipe_modules.chromeos.build_reporting.build_reporting import BuildReportingProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'checkpoint',
    'cloud_pubsub',
    'easy',
    'signing_utils',
    'cros_tags',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildReportingProperties
