# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test against public methods in the cros_test_sharding module"""

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/raw_io',
    'cros_test_sharding',
]


def RunSteps(api):
  if 'suite' in api.properties:
    suite = api.properties['suite']
  else:
    suite = 'bvt-tast-cq'
  if 'board' in api.properties:
    board = api.properties['board']
  else:
    board = 'drallion'
  if api.properties['test_timing_query_results']:
    test_timing_query_results = {'foo': 20, 'bar': 21, 'buz': 22}
  else:
    test_timing_query_results = api.cros_test_sharding.TestCase.test_times

  # pylint: disable=protected-access
  test_timings = api.cros_test_sharding._update_test_timing_information(
      suite, board)
  #  To Show that this works for real...
  #  uncomment the EXAMPLE section below, then run
  # `../../recipes.py run cros_test_sharding:examples/bq_test`
  #  It will dump the `bq` results test timings which is not the same as
  #  `test_timing_query_results`
  #+BEGIN_EXAMPLE IM_NOT_CRAZY
  # import sys
  # print("test_timings:", file=sys.stderr)
  # for test in test_timings:
  #   print(f'{test}:{test_timings[test]}', file=sys.stderr)
  #+END_EXAMPLE

  assert test_timings == test_timing_query_results


OUTPUT_TEXT_RESULTS = '''name,default_timing_dict
foo,20
bar,21
buz,22
'''
OUTPUT_TEXT_NOROWS = '''name,default_timing_dict'''

OUTPUT_TEXT_NORESULTS = ''''''

OUTPUT_TEXT_MESSEDUPRESULTS = '''name,default_timing_dict
kasdjfasdf'''

QUERY_STEP_TITLE = 'Updating test timing information.Query for test timing information'


def GenTests(api):
  yield api.test(
      'drallion_bvt-tast-cq-results',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_RESULTS),
          stderr=api.raw_io.output_text('bq query failed'),
          retcode=0,
      ),
      api.properties(board='drallion', suite='bvt-tast-cq',
                     test_timing_query_results=True))

  yield api.test(
      'drallion_bvt-tast-cq-noresults',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_NORESULTS),
          stderr=api.raw_io.output_text('bq query failed'),
          retcode=0,
      ),
      api.properties(board='drallion', suite='bvt-tast-cq',
                     test_timing_query_results=False))

  yield api.test(
      'failure-query',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_NORESULTS),
          stderr=api.raw_io.output_text('bq query failed'),
          retcode=4,
      ),
      api.properties(board='drallion', suite='bvt-tast-cq',
                     test_timing_query_results=False))

  yield api.test(
      'messedup-query',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_MESSEDUPRESULTS),
          stderr=api.raw_io.output_text(''),
          retcode=0,
      ),
      api.properties(board='drallion', suite='bvt-tast-cq',
                     test_timing_query_results=False))

  yield api.test(
      'empty-query',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_NOROWS),
          stderr=api.raw_io.output_text(''),
          retcode=0,
      ),
      api.properties(board='drallion', suite='bvt-tast-cq',
                     test_timing_query_results=False))

  yield api.test(
      'none-properties',
      api.step_data(
          QUERY_STEP_TITLE,
          stdout=api.raw_io.output_text(OUTPUT_TEXT_NORESULTS),
          stderr=api.raw_io.output_text(''),
          retcode=0,
      ), api.properties(test_timing_query_results=False))
