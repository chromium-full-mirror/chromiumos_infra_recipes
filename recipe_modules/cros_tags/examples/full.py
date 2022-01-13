# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from PB.go.chromium.org.luci.swarming.proto.api.swarming import StringPair

from PB.recipe_modules.chromeos.cros_tags.examples.test import (
    TestInputProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'cros_tags',
]

PROPERTIES = TestInputProperties


def _string_pairs(*pairs):
  """Convert list of tuples into list of StringPairs."""
  return [StringPair(key=k, value=v) for k, v in pairs]


def RunSteps(api, properties):
  snapshot = bbcommon_pb2.GitilesCommit(host='host', project='proj',
                                        id='deadbeef')
  expected_tags = api.cros_tags.tags(
      **{
          'parent_buildbucket_id': str(api.buildbucket.build.id),
          'snapshot': snapshot.id,
          'commit_position': str(snapshot.position),
          'buildset': 'commit/gitiles/host/proj/+/deadbeef',
          'hide-test-results-in-gerrit': 'true'
      })
  if properties.cq_cl_group_key:
    expected_tags.extend(
        api.cros_tags.tags(cq_cl_group_key=str(properties.cq_cl_group_key)))
  if properties.cq_equivalent_cl_group_key:
    expected_tags.extend(
        api.cros_tags.tags(
            cq_equivalent_cl_group_key=str(
                properties.cq_equivalent_cl_group_key)))

  tags = api.cros_tags.make_schedule_tags(snapshot)

  api.assertions.assertEqual(len(tags), len(expected_tags))
  for tag in tags:
    api.assertions.assertIn(tag, expected_tags)

  api.assertions.assertEqual(api.cros_tags.cq_equivalent_cl_group_key,
                             properties.cq_equivalent_cl_group_key or None)

  api.assertions.assertEqual(api.cros_tags.cq_cl_group_key,
                             properties.cq_cl_group_key or None)

  api.assertions.assertTrue(
      api.cros_tags.has_entry('parent_buildbucket_id',
                              str(api.buildbucket.build.id), tags))
  api.assertions.assertTrue(
      api.cros_tags.has_entry('snapshot', snapshot.id, tags))
  api.assertions.assertFalse(
      api.cros_tags.has_entry('snapshot', snapshot.id + 'x', tags))
  api.assertions.assertFalse(
      api.cros_tags.has_entry('snapshotx', snapshot.id, tags))
  api.assertions.assertTrue(
      api.cros_tags.has_entry('commit_position', str(snapshot.position), tags))

  tags2 = api.cros_tags.make_schedule_tags(snapshot, inherit_buildsets=False)
  expected2 = [x for x in expected_tags if x.key != 'buildset']

  api.assertions.assertEqual(len(expected2), len(tags2))
  for tag in expected2:
    api.assertions.assertTrue(
        api.cros_tags.has_entry(tag.key, tag.value, tags2))

  tags3 = api.buildbucket.tags(baz='foo:bar', cq_cl_tag='ha:lol')
  api.assertions.assertEqual(api.cros_tags.cq_cl_tag_value('foo', tags3), None)
  api.assertions.assertEqual(api.cros_tags.cq_cl_tag_value('ha', tags3), 'lol')

  # Test that retrieve tags works as expected
  api.assertions.assertEqual(
      api.cros_tags.get_values(
          'test-key',
          _string_pairs(('test-key', 'foo')),
      ),
      ['foo'],
  )

  api.assertions.assertEqual(
      api.cros_tags.get_values(
          'test-key',
          _string_pairs(('test-key', 'foo'), ('another-key', 'bar'),
                        ('test-key', 'baz')),
      ),
      ['foo', 'baz'],
  )

  api.assertions.assertEqual(
      api.cros_tags.get_values(
          'key-not-present',
          _string_pairs(('test-key', 'foo')),
          default='default-value',
      ),
      ['default-value'],
  )


def GenTests(api):
  equiv = u'01f806668b9e02978b40f699340d5ad7c0da85fb4446d3421c41e790'
  group = u'099ed4f822eaff88f1f0d0cae8c40f09e212b0672c2497afe9f88449'
  yield api.test(
      'basic', api.cq(run_mode=api.cq.FULL_RUN),
      api.properties(
          TestInputProperties(cq_cl_group_key=group,
                              cq_equivalent_cl_group_key=equiv)),
      api.buildbucket.ci_build(
          project='chromeos', bucket='postsubmit',
          builder='postsubmit-orchestrator',
          tags=api.cros_tags.tags(cq_cl_group_key=group,
                                  cq_equivalent_cl_group_key=equiv)))

  yield api.test(
      'no_group_key_tags', api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='postsubmit-orchestrator'))

  yield api.test(
      'cq-inactive',
      api.buildbucket.ci_build(
          project='chromeos', bucket='postsubmit',
          builder='postsubmit-orchestrator',
          tags=api.cros_tags.tags(cq_equivalent_cl_group_key=equiv)))
