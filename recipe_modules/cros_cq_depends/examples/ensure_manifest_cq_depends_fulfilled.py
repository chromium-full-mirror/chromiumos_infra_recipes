# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'cros_source',
    'cros_cq_depends',
    'gerrit',
    'repo',
    'src_state',
]



def RunSteps(api):
  api.cros_source.configure_builder()
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

  changes = [
      GerritChange(change=1, host='chromium-review.googlesource.com'),
      GerritChange(change=2, host='chromium-review.googlesource.com'),
      GerritChange(change=3, host='chromium-review.googlesource.com'),
  ]

  value_dict = {
      1: {
          # This project name corresponds to a repo test_data project.
          'change_id': '1',
          'project': 'project-c',
          'branch': api.src_state.default_branch,
          'current_revision': 'deadbeef',
      },
      2: {
          # Imitates a project outside the chromiumos checkout.
          'change_id': '2',
          'project': 'not-a-project',
          'branch': api.src_state.default_branch,
          'current_revision': 'deadbeef',
      },
      3: {
          # Malformed response.
          'change_id': '3',
      }
  }

  yield api.test(
      'has-simple-dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output_text(
              'deadbeef\x1FCq-Depend: chromium:12345\x00')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'ensure manifest cq-depend fulfilled (2)', changes, value_dict),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=0),
      api.post_check(verify_dep_fetched, 2, 12345),
  )

  yield api.test(
      'has-fulfilled-dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output_text('deadbeef\x1FCq-Depend: chromium:12345,'
                                        'chromium:IAmNotAnInteger,'
                                        'chrome-internal:67890\x00')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'ensure manifest cq-depend fulfilled (2)', changes, value_dict),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=0),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
  )

  yield api.test(
      'has-missing-dep',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output_text('deadbeef\x1FCq-Depend:chromium:12345,'
                                        'chromium:IAmNotAnInteger,'
                                        'chrome-internal:67890\x00')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'ensure manifest cq-depend fulfilled (2)', changes, value_dict),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=128),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      # TODO (b/275363240): audit this test.
      status='FAILURE')

  yield api.test(
      'has-missing-dep-permitted',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output_text('deadbeef\x1FCq-Depend:chromium:12345,'
                                        'chromium:IAmNotAnInteger,'
                                        'chrome-internal:67890\x00')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'ensure manifest cq-depend fulfilled (2)', changes, value_dict),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=128),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
      api.properties(
          **{'$chromeos/cros_cq_depends': {
              'allow_missing_depends': True
          }}),
  )

  yield api.test(
      'find-project-path-fails',
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).git log',
          stdout=api.raw_io.output_text('deadbeef\x1FCq-Depend:chromium:12345,'
                                        'chromium:IAmNotAnInteger,'
                                        'chrome-internal:67890\x00')),
      api.gerrit.set_gerrit_fetch_changes_response(
          'ensure manifest cq-depend fulfilled (2)', changes, value_dict),
      api.step_data(
          'ensure manifest cq-depend fulfilled (2).repo forall (2)',
          stdout=api.raw_io.output_text('c|src/c|cros|refs/heads/other-branch'
                                        '|refs/heads/another-branch')),
      api.post_check(verify_dep_fetched, 2, 12345),
      api.post_check(verify_dep_fetched, 2, 67890),
  )
