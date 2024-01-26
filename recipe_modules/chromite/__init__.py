# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the chromite module."""

DEPS = {
    'buildbucket': 'recipe_engine/buildbucket',
    'context': 'recipe_engine/context',
    'file': 'recipe_engine/file',
    'legacy_annotation': 'recipe_engine/legacy_annotation',
    'path': 'recipe_engine/path',
    'properties': 'recipe_engine/properties',
    'step': 'recipe_engine/step',
    'bot_update': 'depot_tools/bot_update',
    'gclient': 'depot_tools/gclient',
    'tryserver': 'depot_tools/tryserver',

    # Our modules.
    'cros_gitiles': 'gitiles',
    'goma': 'goma',
    'repo': 'repo',
}


# TODO(phajdan.jr): provide coverage (http://crbug.com/693058).
DISABLE_STRICT_COVERAGE = True
