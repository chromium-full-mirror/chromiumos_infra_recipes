# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'cros_source',
]


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), \
      api.context(cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache(projects=['chromiumos/config'])


def GenTests(api):
  yield api.test('basic')
