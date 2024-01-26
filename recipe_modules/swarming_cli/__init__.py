# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the swarming_cli module."""

DEPS = [
    'easy',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
]
