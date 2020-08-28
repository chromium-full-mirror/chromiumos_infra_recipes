# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/raw_io',

  'cros_source',
  'cros_cq_depends',
  'repo',
]


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):
    api.cros_source.ensure_synced_cache()
    api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled([])

    diffs = [api.repo.ManifestDiff('NAME', 'PATH', 'FROM_REV', 'TO_REV')]
    api.cros_cq_depends.ensure_manifest_cq_depends_fulfilled(diffs)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'has_fulfilled_dep',
      api.step_data('ensure manifest cq-depend fulfilled (2).git log',
                    stdout=api.raw_io.output(
                        'deadbeef\x1ECq-Depend: chromium:12345,'
                        'chromium:IAmNotAnInteger,'
                        'chrome-internal:67890\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=0),
  )

  yield api.test(
      'has_missing_dep',
      api.step_data('ensure manifest cq-depend fulfilled (2).git log',
                    stdout=api.raw_io.output(
                        'deadbeef\x1ECq-Depend:chromium:12345,'
                        'chromium:IAmNotAnInteger,'
                        'chrome-internal:67890\x00')),
      api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                    retcode=128),
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
  )
