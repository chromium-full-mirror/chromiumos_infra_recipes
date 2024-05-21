# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deps and properties for the image_builder_failures module."""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'failures',
    'naming',
    'src_state',
    'urls',
]
