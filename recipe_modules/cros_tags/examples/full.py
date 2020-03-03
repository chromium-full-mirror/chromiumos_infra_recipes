# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_tags',
]

def RunSteps(api):
  snapshot = bbcommon_pb2.GitilesCommit(id='deadbeef')
  expected_tags = [
      {
          'value': str(api.buildbucket.build.id),
          'key': 'parent_buildbucket_id'
      },
      {
          'value': snapshot.id,
          'key': 'snapshot'
      },
  ]

  tags = api.cros_tags.make_schedule_tags(snapshot)

  api.assertions.assertEqual(tags, expected_tags)

  tags = [bbcommon_pb2.StringPair(key=d['key'], value=d['value'])
          for d in expected_tags]

  api.assertions.assertTrue(
      api.cros_tags.has_entry('parent_buildbucket_id',
                              str(api.buildbucket.build.id), tags))
  api.assertions.assertTrue(
      api.cros_tags.has_entry('snapshot', snapshot.id, tags))
  api.assertions.assertFalse(
      api.cros_tags.has_entry('snapshot', snapshot.id + 'x', tags))
  api.assertions.assertFalse(
      api.cros_tags.has_entry('snapshotx', snapshot.id, tags))

def GenTests(api):
  yield (api.test('basic') + #
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='postsubmit-orchestrator'))
