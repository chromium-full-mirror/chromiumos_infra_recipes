# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'metadata_json',
]


def RunSteps(api):
  api.metadata_json.add_default_entries()


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='cq', builder='amd64-generic-cq'))
