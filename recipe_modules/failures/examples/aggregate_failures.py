# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from collections import defaultdict

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution \
  import CqFailureAttribute, FaultAttributionProperties, SnapshotProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/cv',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  results = api.failures.Results(failures=[], successes={})
  final_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(final_result.status, common_pb2.SUCCESS)
  api.assertions.assertEqual(final_result.summary_markdown, '')
  results.failures = [
      api.failures.Failure(kind='kind', title='title',
                           link_map={'title': 'url'}, fatal=False, id='my id'),
  ]
  final_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(final_result.status, common_pb2.SUCCESS)
  api.assertions.assertIn('1 non-critical kind failed',
                          final_result.summary_markdown)

  results.failures = [
      api.failures.Failure(kind='build', title='build-a',
                           link_map={'build page': 'build-a.com'}, fatal=True,
                           id='id-0'),
      api.failures.Failure(kind='build', title='build-b',
                           link_map={'build page': 'build-b.com'}, fatal=True,
                           id='id-1'),
      api.failures.Failure(kind='test', title='test-a',
                           link_map={'subtest-1': 'test-a.com'}, fatal=True,
                           id='id-2'),
      api.failures.Failure(kind='hw test', title='test-b',
                           link_map={'test-b': 'test-b.com'}, fatal=True,
                           id='id-3'),
      api.failures.Failure(kind='build', title='build-c',
                           link_map={'test-c': 'test-c.com'}, fatal=False,
                           id='id-4'),
      api.failures.Failure(kind='test', title='test-c',
                           link_map={'test-c': 'test-c.com'}, fatal=False,
                           id='id-5'),
      api.failures.Failure(kind='different_kind_of_test', title='test-x',
                           link_map={'test-x': 'test-x.com'}, fatal=True,
                           id='id-6'),
      api.failures.Failure(kind='very_different_kind_of_test', title='test-y',
                           link_map={'test-y': 'test-y.com'}, fatal=False,
                           id='id-7'),
      api.failures.Failure(kind='hw test', title='test-1',
                           link_map={'test-1': 'test-1.com'}, fatal=True,
                           id='id-8'),
      api.failures.Failure(
          kind='hw test', title='test-2', link_map={
              'test-2': 'test-2.com',
              'test-shard-0 (timed out)': 'shard.com'
          }, fatal=True, id='id-9'),
      api.failures.Failure(kind='hw test', title='no-links-test', link_map={},
                           fatal=True, id='id-10'),
  ]
  results.successes = {'build': 28, 'very_different_kind_of_test': 1}

  test_properties_to_fault_attribute = defaultdict(lambda: None)
  comparison_snapshot_properties = SnapshotProperties()
  comparison_snapshot_properties.source_build_id = 12345
  comparison_snapshot_properties.source_started_unix_timestamp = 1693893626

  hw_test_fault_attribute = FaultAttributionProperties()
  hw_test_fault_attribute.test_name = 'test-1'
  hw_test_fault_attribute.snapshot_comparison_fault_attribution = CqFailureAttribute.DIFFERING_FAILURE_FOUND
  hw_test_fault_attribute.comparison_snapshot.CopyFrom(
      comparison_snapshot_properties)

  hw_test_fault_attribute2 = FaultAttributionProperties()
  hw_test_fault_attribute2.test_name = 'test-2'
  hw_test_fault_attribute2.snapshot_comparison_fault_attribution = CqFailureAttribute.SUCCESS_FOUND
  hw_test_fault_attribute2.comparison_snapshot.CopyFrom(
      comparison_snapshot_properties)

  hw_test_fault_attribute3 = FaultAttributionProperties()
  hw_test_fault_attribute3.test_name = 'test-b'
  hw_test_fault_attribute3.snapshot_comparison_fault_attribution = CqFailureAttribute.MATCHING_FAILURE_FOUND
  hw_test_fault_attribute3.comparison_snapshot.CopyFrom(
      comparison_snapshot_properties)

  test_properties_to_fault_attribute[('test-1', 'test-1', '')] \
    = hw_test_fault_attribute
  test_properties_to_fault_attribute[('test-2', 'test-2', '')] \
    = hw_test_fault_attribute2
  test_properties_to_fault_attribute[('test-b', 'test-b', '')] \
    = hw_test_fault_attribute3
  api.failures.set_test_variant_to_fault_attribute(
      test_properties_to_fault_attribute)

  final_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(final_result.status, common_pb2.FAILURE)
  api.assertions.assertIn(
      '''\
2 out of 30 builds failed (1 additional non-critical failure)

- build-a: [build page](build-a.com)

- build-b: [build page](build-b.com)

1 out of 1 different_kind_of_test failed

- test-x: [test-x](test-x.com)

3 hw tests failed. 2 hw test suites failed with incomplete results

- no-links-test

- test-1

    - [test-1](test-1.com) | different failure already present as of [2023-09-05 06:00:26](https://ci.chromium.org/ui/b/12345/test-results?q=ExactID:test-1)

- test-2

    - [test-2](test-2.com)

    - [test-shard-0 (timed out)](shard.com)

- test-b

    - [test-b](test-b.com) | identical failure already present as of [2023-09-05 06:00:26](https://ci.chromium.org/ui/b/12345/test-results?q=ExactID:test-b)

1 out of 1 test failed (1 additional non-critical failure)

- test-a: [subtest-1](test-a.com)

1 non-critical very_different_kind_of_test failed



📢: If this CQ attempt failed on an unrelated test, please read go/chromeos-cq-customization-psa''',
      final_result.summary_markdown)

  results.failures = [
      api.failures.Failure(kind='build', title='build-a', link_map={
          'build page': 'build-a.com'
      }, fatal=True, id='my id'),
  ] * 50
  final_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(final_result.status, common_pb2.FAILURE)
  api.assertions.assertIn('40 others', final_result.summary_markdown)

  # Try to exceed the 4000 limit with really long test links.
  really_long_text = 'All code and no test makes failures a dull module.' * 4000
  results.failures = [
      api.failures.Failure(
          kind='hw test', title='test-a', link_map={
              'subtest-1': 'testlink.com',
              'subtest-2': really_long_text,
          }, fatal=True, id='id-3'),
  ]
  final_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(final_result.status, common_pb2.FAILURE)
  api.assertions.assertIn(
      '2 hw tests failed\n\n- test-a\n\n    - [subtest-1](testlink.com)\n\n...',
      final_result.summary_markdown)
  api.failures.set_exoneration_markdown(markdown_txt='some suites exonerated')

  results = api.failures.Results(failures=[], successes={})
  infra_failure1 = api.failures.Failure(kind='build', title='build-a',
                                        link_map={'build page': 'build-a.com'},
                                        fatal=True, id='id-0',
                                        type=common_pb2.INFRA_FAILURE)
  infra_failure2 = api.failures.Failure(kind='build', title='build-a1',
                                        link_map={'build page': 'build-a.com'},
                                        fatal=True, id='id-1',
                                        type=common_pb2.INFRA_FAILURE)
  regular_failure = api.failures.Failure(kind='build', title='build-b',
                                         link_map={'build page': 'build-b.com'},
                                         fatal=True, id='id-2',
                                         type=common_pb2.FAILURE)
  results.failures = [infra_failure1, infra_failure2]
  infra_failure_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(infra_failure_result.status,
                             common_pb2.INFRA_FAILURE)

  results.failures.append(regular_failure)
  mix_failure_result = api.failures.aggregate_failures(results)
  api.assertions.assertEqual(mix_failure_result.status, common_pb2.FAILURE)

def GenTests(api):
  yield api.test('basic', api.cv(run_mode=api.cv.FULL_RUN))
