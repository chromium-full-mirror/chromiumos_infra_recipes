# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for cq exoneration."""

from PB.recipe_modules.chromeos.exonerate.exonerate import ExonerateProperties

DEPS = [
    'depot_tools/gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/luci_analysis',
    'recipe_engine/step',
    'cros_history',
    'cros_infra_config',
    'easy',
    'failures',
    'exoneration_util',
    'naming',
    'rdb_util',
    'src_state',
    'urls',
]


PROPERTIES = ExonerateProperties
