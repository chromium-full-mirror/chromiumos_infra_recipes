# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for the bot_scaling module."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/futures',
    'recipe_engine/json',
    'recipe_engine/led',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_history',
    'cros_infra_config',
    'easy',
    'gce_provider',
    'swarming_cli',
]
