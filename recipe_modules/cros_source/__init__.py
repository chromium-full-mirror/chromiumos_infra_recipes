# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_source module."""

from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'cas': 'recipe_engine/cas',
    'context': 'recipe_engine/context',
    'file': 'recipe_engine/file',
    'path': 'recipe_engine/path',
    'properties': 'recipe_engine/properties',
    'raw_io': 'recipe_engine/raw_io',
    'step': 'recipe_engine/step',
    'time': 'recipe_engine/time',
    'depot_gitiles': 'depot_tools/gitiles',
    'bot_cost': 'bot_cost',
    'cros_build_api': 'cros_build_api',
    'cros_infra_config': 'cros_infra_config',
    'easy': 'easy',
    'gcloud': 'gcloud',
    'gerrit': 'gerrit',
    'git': 'git',
    'gitiles': 'gitiles',
    'git_footers': 'git_footers',
    'gsutil': 'depot_tools/gsutil',
    'overlayfs': 'overlayfs',
    'repo': 'repo',
    'src_state': 'src_state',
    'test_util': 'test_util',
}


PROPERTIES = CrosSourceProperties
