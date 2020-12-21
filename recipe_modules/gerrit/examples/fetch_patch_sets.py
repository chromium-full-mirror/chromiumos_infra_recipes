# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
    'src_state',
]

step_name = 'testing'
changes = [
    GerritChange(host='chromium-review.googlesource.com', change=91827,
                 patchset=1),
    GerritChange(host='example.com', change=2, patchset=3),
]


# Values with a leading underscore in the name are for validation purposes only
# and are not used by in generating test data.
def _get_values_dict(api):
  return {
      # Negative value so that we get the default values, but can verify them
      # easily.
      -91827:
          dict(
              status='NEW',
              created='2017-01-30 13:11:20.000000000',
              updated='2017-02-01 13:11:20.000000000',
              submitted='2017-02-02 13:11:20.000000000',
              change_id='Ideadbeef',
              current_revision='f000' * 10,
              project='chromium/src',
              has_review_started=False,
              branch=api.src_state.default_branch,
              subject='Change title',
              message='\n'.join(
                  ['a quick description', '', 'Change-Id: deadbeef', '']),
              url='https://chromium.googlesource.com/chromium/src',
              ref='refs/changes/27/91827/1',
              files={'my/fake/file': dict(status='A', size_delta=0, size=0)},
              hashtags=[],
              messages=[],
              _display_id='chromium:91827',
              _display_url='https://chromium-review.googlesource.com/c/91827',
              _short_host='chromium',
              _patch_set=1,
              _host='chromium-review.googlesource.com',
          ),
      2:
          dict(
              status='OLD',
              created='2020-08-01 11:11:11.000000000',
              updated='2020-08-02 12:12:22.000000000',
              submitted='2020-08-02 12:12:22.000000000',
              change_id='Ib767aac2',
              current_revision='b000' * 10,
              project='new-project',
              has_review_started=True,
              branch='release',
              subject='Different title',
              message='\n'.join(
                  ['Different title', '', 'Change-Id: Ib767aac2', '']),
              url='https://example.com/project-path',
              ref='refs/something/02/2/3',
              files={'their/fake/file': dict(status='A', size_delta=0, size=0)},
              hashtags=["foo", "bar"],
              messages=[{
                  'id': "1",
                  "message": "hello!"
              }, {
                  'id': "2",
                  "message": "goodbye."
              }],
              _display_id='example.com:2',
              _display_url='https://example.com/c/2',
              _short_host='example.com',
              _patch_set=3,
              _host='example.com',
          )
  }


def RunSteps(api):
  # TODO(evanhernandez): These tests could use some work.

  with api.step.nest(step_name):
    patches = api.gerrit.fetch_patch_sets(changes)
  api.assertions.assertEqual(len(patches), len(changes))

  values_dict = _get_values_dict(api)
  for patch in patches:
    values = values_dict.get(patch.change_id, values_dict.get(-patch.change_id))
    api.assertions.assertEqual(patch.project, values['project'])
    api.assertions.assertEqual(patch.branch, values['branch'])
    api.assertions.assertEqual(patch.subject, values['subject'])
    api.assertions.assertEqual(patch.git_fetch_url, values['url'])
    api.assertions.assertEqual(patch.git_fetch_ref, values['ref'])
    api.assertions.assertEqual(patch.short_host, values['_short_host'])
    api.assertions.assertEqual(patch.display_id, values['_display_id'])
    api.assertions.assertEqual(patch.patch_set, values['_patch_set'])
    api.assertions.assertEqual(patch.display_url, values['_display_url'])
    api.assertions.assertEqual(patch.created, values['created'])
    api.assertions.assertEqual(patch.updated, values['updated'])
    api.assertions.assertEqual(patch.submitted, values['submitted'])
    api.assertions.assertEqual(patch.hashtags, values['hashtags'])
    api.assertions.assertEqual(patch.messages, values['messages'])
    api.assertions.assertEqual(patch.current_revision,
                               values['current_revision'])
    for fname in values['files']:
      api.assertions.assertIn(fname, patch.file_infos)
    api.assertions.assertEqual(patch.commit_info,
                               {'message': values['message']})
    api.assertions.assertEqual(
        patch.to_gerrit_change_proto(),
        GerritChange(host=patch.host, change=patch.change_id,
                     project=patch.project, patchset=patch.patch_set))

  patch = patches[0]
  # Missing FetchInfo.
  del patch._rev_info['fetch']
  api.assertions.assertEqual(
      patch.git_fetch_url,
      'https://chromium-review.googlesource.com/chromium/src')
  api.assertions.assertEqual(patch.git_fetch_ref, 'refs/changes/27/91827/1')

  # Missing result
  try:
    api.gerrit.fetch_patch_sets(changes, test_output_data={'changes': [{}]})
  except api.step.StepFailure:
    pass

  api.gerrit.test_api.test_patch_set()


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.set_gerrit_fetch_changes_response(step_name, changes,
                                                   _get_values_dict(api)))
