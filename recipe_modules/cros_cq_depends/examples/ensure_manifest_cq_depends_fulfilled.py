# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'cros_cq_depends',
    'repo',
]

import json
from recipe_engine import post_process


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache()
    api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled([])

    diffs = [api.repo.ManifestDiff('NAME', 'PATH', 'FROM_REV', 'TO_REV')]
    api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled(diffs)


def GenTests(api):
  yield api.test('basic')

  def verify_dep_fetched(check, steps, iteration, cl_num):
    iter_str = ' (%d)' % iteration if iteration > 1 else ''
    name = ('ensure manifest cq-depend fulfilled%s.gerrit-fetch-changes' %
            iter_str)
    data = json.loads(steps[name].stdin)
    return check(cl_num in [x['change_number'] for x in data['changes']])

  yield api.test(
      'has_simple_dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output(
              'deadbeef\x1ECq-Depend: chromium:12345\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=0),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'has_fulfilled_dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output('deadbeef\x1ECq-Depend: chromium:12345,'
                                   'chromium:IAmNotAnInteger,'
                                   'chrome-internal:67890\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=0),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'has_missing_dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output('deadbeef\x1ECq-Depend:chromium:12345,'
                                   'chromium:IAmNotAnInteger,'
                                   'chrome-internal:67890\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=128),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      api.post_check(post_process.StatusAnyFailure),
  )

  yield api.test(
      'has_missing_dep-permitted',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output('deadbeef\x1ECq-Depend:chromium:12345,'
                                   'chromium:IAmNotAnInteger,'
                                   'chrome-internal:67890\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=128),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      api.properties(
          **{"$chromeos/cros_cq_depends": {
              "allow_missing_depends": True
          }}),
      api.post_check(post_process.StatusSuccess),
  )

  yield api.test(
      'find_project_path_fails',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output('deadbeef\x1ECq-Depend:chromium:12345,'
                                   'chromium:IAmNotAnInteger,'
                                   'chrome-internal:67890\x00')),
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).repo forall (2)',
          stdout=api.raw_io.output('c|src/c|cros|refs/heads/other-branch'
                                   '|refs/heads/another-branch')),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      api.post_check(post_process.StatusSuccess),
  )
