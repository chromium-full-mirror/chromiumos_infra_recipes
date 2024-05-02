# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for auto-retry functions."""

from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cv',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'buildbucket_stats',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'deferrals',
    'easy',
    'exonerate',
    'exoneration_util',
    'gerrit',
    'git_footers',
    'looks_for_green',
    'naming',
    'skylab_results',
    'tast_results',
]


PROPERTIES = AutoRetryUtilProperties
