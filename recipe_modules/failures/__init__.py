# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for tracking, filtering, and aggregating failures.

Provides a way to catch and filter exceptions, track failures, and aggregate
failures from child builds. Also provides the ability to distinguish between
build failures and infrastructure failures.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'easy',
    'failures_util',
    'naming',
    'src_state',
    'urls',
]
