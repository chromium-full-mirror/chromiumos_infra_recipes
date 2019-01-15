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
]


def RunSteps(api):
  to_manifest = """
    <manifest>
      <project path="SAMPLE" revision="TO_REV"/>
    </manifest>
  """

  with api.tempfile.temp_dir('foo') as foo, api.context(cwd=foo):

    # No previous manifest case
    api.depends.ensure_manifest_cq_depends_fulfilled('REF', to_manifest)

    # With previous manifest case
    api.path.mock_add_paths(foo.join('snapshot.xml'))
    api.depends.ensure_manifest_cq_depends_fulfilled('REF', to_manifest)


def GenTests(api):
  yield api.test('basic')

  yield (api.test('missing from XML') +  #
         api.step_data('ensure manifest cq-depends fulfilled.git show',
                       retcode=128))

  yield (api.test('has fulfilled dep') +  #
         api.step_data('ensure manifest cq-depends fulfilled.git log',
                       stdout=api.raw_io.output(
                           'deadbeef\x1ECQ-DEPEND=12345,*67890\x00')) +  #
         api.step_data('ensure manifest cq-depends fulfilled.git merge-base',
                       retcode=0))

  yield (api.test('has missing dep') +  #
         api.step_data('ensure manifest cq-depends fulfilled.git log',
                       stdout=api.raw_io.output(
                           'deadbeef\x1ECQ-DEPEND=12345,*67890\x00')) +  #
         api.step_data('ensure manifest cq-depends fulfilled.git merge-base',
                       retcode=128))
