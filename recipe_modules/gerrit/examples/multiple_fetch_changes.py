# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
    'src_state',
]


changes = [
    GerritChange(host='chromium-review.googlesource.com', change=1,
                 project='fake-project-1', patchset=1),
    GerritChange(host='chromium-review.googlesource.com', change=2,
                 project='fake-project-2', patchset=2),
]


def _get_values_dict():
  return {
      1: {
          'change_id': '1',
          'created': '2020-10-22 18:54:00.000000000',
          'branch': 'fake-branch-1',
          'project': 'fake-project-1',
          'revision_info': {
              '_number': 1,
              'ref': 'refs/change/foo',
              'files': {
                  'foo.rs': {
                      'status': 'A',
                      'size_delta': 0,
                      'size': 0
                  },
                  'bar.txt': {
                      'status': 'A',
                      'size_delta': 0,
                      'size': 0
                  },
              }
          }
      },
      2: {
          'change_id': '2',
          'created': '2020-10-22 18:54:00.000000000',
          'branch': 'fake-branch-2',
          'project': 'fake-project-2',
          'revision_info': {
              '_number': 2,
              'ref': 'refs/change/foo',
              'files': {
                  'foo.rs': {
                      'status': 'A',
                      'size_delta': 0,
                      'size': 0
                  },
                  'bar.txt': {
                      'status': 'A',
                      'size_delta': 0,
                      'size': 0
                  },
              }
          }
      }
  }


def RunSteps(api):
  with api.step.nest('test multiple'):
    patches = []
    for commit in changes:
      patches.append(api.gerrit.fetch_patch_set_from_change(commit))

  values_dict = _get_values_dict()
  for patch in patches:
    values = values_dict.get(patch.change_id, values_dict.get(patch.change_id))
    api.assertions.assertEqual(patch.project, values['project'])
    api.assertions.assertEqual(patch.branch, values['branch'])
    api.assertions.assertEqual(patch.created, values['created'])
    for fname in values['revision_info']['files']:
      api.assertions.assertIn(fname, patch.file_infos)


def GenTests(api):
  yield api.test(
      'multiple-calls',
      api.gerrit.set_gerrit_fetch_changes_response('test multiple',
                                                   [changes[0]],
                                                   _get_values_dict()),
      api.gerrit.set_gerrit_fetch_changes_response('test multiple',
                                                   [changes[1]],
                                                   _get_values_dict(),
                                                   iteration=2),
  )
