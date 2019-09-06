# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_tags',
]

def RunSteps(api):
  tags = api.cros_tags.make_schedule_tags()
  api.assertions.assertEqual(
      tags, [{'value': str(api.buildbucket.build.id),
              'key': 'parent_buildbucket_id'}])

def GenTests(api):
  yield (api.test('basic') + #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='postsubmit-orchestrator'))
