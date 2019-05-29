# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'recipe_engine/context',
  'recipe_engine/path',
  'recipe_engine/raw_io',
  'recipe_engine/tempfile',

  'depends',
  'repo',
]


def RunSteps(api):

    api.depends.ensure_manifest_cq_depends_fulfilled([])

    diffs = [api.repo.ManifestDiff('NAME', 'PATH', 'FROM_REV', 'TO_REV')]
    api.depends.ensure_manifest_cq_depends_fulfilled(diffs)

def GenTests(api):
  yield api.test('basic')

  yield (api.test('has fulfilled dep') +  #
         api.step_data('ensure manifest cq-depend fulfilled (2).git log',
                       stdout=api.raw_io.output(
                           'deadbeef\x1ECq-Depend: chromium:12345,'
                           'chrome-internal:67890\x00')) +  #
         api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                       retcode=0))

  yield (api.test('has missing dep') +  #
         api.step_data('ensure manifest cq-depend fulfilled (2).git log',
                       stdout=api.raw_io.output(
                           'deadbeef\x1ECq-Depend:chromium:12345,'
                           'chrome-internal:67890\x00')) +  #
         api.step_data('ensure manifest cq-depend fulfilled (2).git merge-base',
                       retcode=128))
