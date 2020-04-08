# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'metadata_json',
]


def RunSteps(api):
  api.metadata_json.add_default_entries()
  metadata = api.metadata_json.get_metadata()
  api.assertions.assertEqual(metadata['builder-name'], 'amd64-generic-cq')


def GenTests(api):
  md_build = api.buildbucket.try_build_message(bucket='cq',
                                               builder='amd64-generic-cq')
  yield (api.test('basic') +  # 
         api.buildbucket.simulated_get(md_build, 'buildbucket.get') +  #
         api.buildbucket.ci_build(project='chromeos', bucket='cq',
                                  builder='amd64-generic-cq'))
