# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related operations (e.g. paygen, signing)."""

from PB.recipe_modules.chromeos.cros_release.cros_release import CrosReleaseProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'build_reporting',
    'builder_metadata',
    'checkpoint',
    'conductor',
    'cros_artifacts',
    'cros_infra_config',
    'cros_release_util',
    'cros_source',
    'cros_test_plan',
    'cros_version',
    'easy',
    'failures',
    'gerrit',
    'git',
    'git_footers',
    'gobin',
    'paygen_orchestration',
    'repo',
    'signing',
    'skylab',
    'src_state',
]


PROPERTIES = CrosReleaseProperties
