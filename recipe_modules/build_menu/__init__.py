# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for build-menu functions."""

from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'recipe_engine/uuid',
    'depot_tools/gsutil',
    'bot_cost',
    'chrome',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_prebuilts',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'cros_tags',
    'cros_version',
    'easy',
    'failures',
    'git_footers',
    'metadata',
    'metadata_json',
    'observability_image_size',
    'src_state',
    'sysroot_archive',
    'sysroot_util',
    'test_util',
    'urls',
    'workspace_util',
]


PROPERTIES = BuildMenuProperties
