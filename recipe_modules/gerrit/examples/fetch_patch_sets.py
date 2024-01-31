# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine.recipe_api import InfraFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'gerrit',
    'src_state',
]


CHANGES = [
    GerritChange(host='chromium-review.googlesource.com', change=91827,
                 patchset=1),
    GerritChange(host='example.com', change=2, patchset=3),
    GerritChange(host='example.com', change=3, patchset=4),
]


# Values with a leading underscore in the name are for validation purposes only
# and are not used by in generating test data.
def _get_values_dict(api):
  return {
      # Negative value so that we get the default values, but can verify them
      # easily.
      -91827: {
          'status':
              'NEW',
          'created':
              '2017-01-30 13:11:20.000000000',
          'updated':
              '2017-02-01 13:11:20.000000000',
          'submitted':
              '',
          'submittable':
              False,
          'unresolved_comment_count':
              0,
          'change_id':
              'Ideadbeef',
          'current_revision':
              'f000' * 10,
          'patch_set':
              1,
          'project':
              'chromium/src',
          'has_review_started':
              False,
          'work_in_progress':
              False,
          'patch_set_revision':
              'f000' * 10,
          'branch':
              api.src_state.default_branch,
          'subject':
              'Change title',
          'topic':
              'Change topic',
          'message':
              '\n'.join(['a quick description', '', 'Change-Id: deadbeef', '']),
          'labels':
              None,
          'url':
              'https://chromium.googlesource.com/chromium/src',
          'ref':
              'refs/changes/27/91827/1',
          'files': {
              'my/fake/file': {
                  'status': 'A',
                  'size_delta': 0,
                  'size': 0
              },
          },
          'hashtags': [],
          'messages': [],
          '_display_id':
              'chromium:91827',
          '_display_url':
              'https://chromium-review.googlesource.com/c/91827',
          '_short_host':
              'chromium',
          '_patch_set':
              1,
          '_host':
              'chromium-review.googlesource.com',
      },
      2: {
          'status':
              'MERGED',
          'created':
              '2020-08-01 11:11:11.000000000',
          'updated':
              '2020-08-02 12:12:22.000000000',
          'submitted':
              '2020-08-02 12:12:22.000000000',
          'submittable':
              False,
          'unresolved_comment_count':
              2,
          'change_id':
              'Ib767aac2',
          'current_revision':
              'b000' * 10,
          'patch_set':
              3,
          'project':
              'new-project',
          'has_review_started':
              True,
          'work_in_progress':
              False,
          'patch_set_revision':
              'b000' * 10,
          'branch':
              'release',
          'subject':
              'Different title',
          'topic':
              'topic2',
          'message':
              '\n'.join(['Different title', '', 'Change-Id: Ib767aac2', '']),
          'url':
              'https://example.com/project-path',
          'ref':
              'refs/something/02/2/3',
          'files': {
              'their/fake/file': {
                  'status': 'A',
                  'size_delta': 0,
                  'size': 0
              },
          },
          'hashtags': ['foo', 'bar'],
          'labels': {},
          'messages': [{
              'id': '1',
              'message': 'hello!'
          }, {
              'id': '2',
              'message': 'goodbye.'
          }],
          '_display_id':
              'example.com:2',
          '_display_url':
              'https://example.com/c/2',
          '_short_host':
              'example.com',
          '_host':
              'example.com',
      },
      3: {
          'status':
              'ABANDONED',
          'created':
              '2020-08-01 11:11:11.000000000',
          'updated':
              '2020-08-02 12:12:22.000000000',
          'submitted':
              '',
          'submittable':
              False,
          'unresolved_comment_count':
              0,
          'change_id':
              'Ib767aac3',
          'current_revision':
              'c000' * 10,
          'patch_set':
              4,
          'project':
              'new-project',
          'has_review_started':
              True,
          'work_in_progress':
              True,
          'patch_set_revision':
              'c000' * 10,
          'branch':
              'release',
          'subject':
              'Different title',
          'topic':
              'topic3',
          'message':
              '\n'.join(['Different title', '', 'Change-Id: Ib767aac3', '']),
          'url':
              'https://example.com/project-path',
          'ref':
              'refs/something/02/3/4',
          'files': {
              'their/fake/file': {
                  'status': 'A',
                  'size_delta': 0,
                  'size': 0
              },
          },
          'hashtags': ['foo', 'bar'],
          'labels': {
              'Code-Review': {
                  'optional': True,
                  'all': [
                      {
                          '_account_id': 1234567,
                          'value': 0
                      },
                      {
                          '_account_id': 2345678,
                          'value': 2
                      },
                  ],
                  'values': {
                      ' 0': 'No score',
                      '+1': 'Looks good to me, but someone else must approve',
                      '+2': 'Looks good to me, approved',
                      '-1': 'I would prefer that you did not submit this',
                      '-2': 'Do not submit'
                  }
              },
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 2
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              }
          },
          'messages': [{
              'id': '1',
              'message': 'hello!'
          }, {
              'id': '2',
              'message': 'goodbye.'
          }],
          '_display_id':
              'example.com:3',
          '_display_url':
              'https://example.com/c/3',
          '_short_host':
              'example.com',
          '_host':
              'example.com',
      },
      4: {
          'status':
              'NEW',
          'created':
              '2020-08-01 11:11:11.000000000',
          'updated':
              '2020-08-02 12:12:22.000000000',
          'submitted':
              '',
          'submittable':
              False,
          'unresolved_comment_count':
              2,
          'change_id':
              'Ib767aac2',
          'current_revision':
              'b000' * 10,
          'patch_set':
              3,
          'project':
              'new-project',
          'has_review_started':
              True,
          'work_in_progress':
              False,
          'patch_set_revision':
              'b000' * 10,
          'branch':
              'release',
          'subject':
              'Different title',
          'topic':
              'topic2',
          'message':
              '\n'.join(['Different title', '', 'Change-Id: Ib767aac2', '']),
          'url':
              'https://example.com/project-path',
          'ref':
              'refs/something/02/2/3',
          'files': {
              'their/fake/file': {
                  'status': 'A',
                  'size_delta': 0,
                  'size': 0
              },
          },
          'hashtags': ['foo', 'bar'],
          'labels': {
              'Code-Review': {
                  'optional': True,
                  'all': [
                      {
                          '_account_id': 1234567,
                          'value': 0
                      },
                      {
                          '_account_id': 2345678,
                          'value': -2
                      },
                  ],
                  'values': {
                      ' 0': 'No score',
                      '+1': 'Looks good to me, but someone else must approve',
                      '+2': 'Looks good to me, approved',
                      '-1': 'I would prefer that you did not submit this',
                      '-2': 'Do not submit'
                  }
              },
              'Verified': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1541512,
                      'value': -1
                  }, {
                      '_account_id': 1345347,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'No score',
                      '+1': 'Verified',
                      '-1': 'Fails'
                  }
              },
              'Commit-Queue': {
                  'optional': True,
                  'all': [{
                      '_account_id': 1234567,
                      'value': 0
                  }, {
                      '_account_id': 2345678,
                      'value': 0
                  }],
                  'values': {
                      ' 0': 'Not ready',
                      '+1': 'Dry run',
                      '+2': 'Commit'
                  }
              }
          },
          'messages': [{
              'id': '1',
              'message': 'hello!'
          }, {
              'id': '2',
              'message': 'goodbye.'
          }],
          '_display_id':
              'example.com:2',
          '_display_url':
              'https://example.com/c/2',
          '_short_host':
              'example.com',
          '_host':
              'example.com',
      },
  }


def RunSteps(api):
  with api.step.nest('test fetch_patch_sets'):
    patches = api.gerrit.fetch_patch_sets(CHANGES)
  api.assertions.assertEqual(len(patches), len(CHANGES))

  values_dict = _get_values_dict(api)
  for patch in patches:
    values = values_dict.get(patch.change_id, values_dict.get(-patch.change_id))
    api.assertions.assertEqual(patch.project, values['project'])
    api.assertions.assertEqual(patch.branch, values['branch'])
    api.assertions.assertEqual(patch.subject, values['subject'])
    api.assertions.assertEqual(patch.topic, values['topic'])
    api.assertions.assertEqual(patch.git_fetch_url, values['url'])
    api.assertions.assertEqual(patch.git_fetch_ref, values['ref'])
    api.assertions.assertEqual(patch.short_host, values['_short_host'])
    api.assertions.assertEqual(patch.display_id, values['_display_id'])
    api.assertions.assertEqual(patch.patch_set, values['patch_set'])
    api.assertions.assertEqual(patch.display_url, values['_display_url'])
    api.assertions.assertEqual(patch.created, values['created'])
    api.assertions.assertEqual(patch.updated, values['updated'])
    api.assertions.assertEqual(patch.submitted, values['submitted'])
    api.assertions.assertEqual(patch.submittable, values['submittable'])
    api.assertions.assertEqual(patch.unresolved_comment_count,
                               values['unresolved_comment_count'])
    api.assertions.assertEqual(patch.status, values['status'])
    api.assertions.assertEqual(patch.work_in_progress,
                               values['work_in_progress'])
    api.assertions.assertEqual(patch.hashtags, values['hashtags'])
    api.assertions.assertEqual(patch.messages, values['messages'])
    api.assertions.assertEqual(patch.labels, values['labels'])
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
    api.assertions.assertEqual(
        patch.is_latest_patch_set(),
        values['current_revision'] == values['patch_set_revision'])
    if patch.labels is not None:
      api.assertions.assertEqual(
          patch.has_label_vote('Code-Review', -2),
          any(x['value'] == -2
              for x in values['labels'].get('Code-Review', {}).get('all', [])))
      api.assertions.assertEqual(
          patch.has_default_label_vote('Commit-Queue'),
          all(x['value'] == 0
              for x in values['labels'].get('Commit-Queue', {}).get('all', [])))

  with api.step.nest('test fetch_patch_sets_from_change'):
    for change, patch in zip(CHANGES, patches):
      patch_set = api.gerrit.fetch_patch_set_from_change(change)
      api.assertions.assertEqual(patch_set.change_id, patch.change_id)
      values = values_dict.get(patch.change_id,
                               values_dict.get(-patch.change_id))
      api.assertions.assertEqual(patch.project, values['project'])
      api.assertions.assertEqual(patch.branch, values['branch'])
      api.assertions.assertEqual(patch.subject, values['subject'])
      api.assertions.assertEqual(patch.topic, values['topic'])
      api.assertions.assertEqual(patch.git_fetch_url, values['url'])
      api.assertions.assertEqual(patch.git_fetch_ref, values['ref'])
      api.assertions.assertEqual(patch.short_host, values['_short_host'])
      api.assertions.assertEqual(patch.display_id, values['_display_id'])
      api.assertions.assertEqual(patch.patch_set, values['patch_set'])
      api.assertions.assertEqual(patch.display_url, values['_display_url'])
      api.assertions.assertEqual(patch.created, values['created'])
      api.assertions.assertEqual(patch.updated, values['updated'])
      api.assertions.assertEqual(patch.submitted, values['submitted'])
      api.assertions.assertEqual(patch.submittable, values['submittable'])
      api.assertions.assertEqual(patch.status, values['status'])
      api.assertions.assertEqual(patch.work_in_progress,
                                 values['work_in_progress'])
      api.assertions.assertEqual(patch.hashtags, values['hashtags'])
      api.assertions.assertEqual(patch.messages, values['messages'])
      api.assertions.assertEqual(patch.current_revision,
                                 values['current_revision'])

  patch = patches[0]
  # Missing FetchInfo.
  del patch._rev_info['fetch']  # pylint: disable=protected-access
  api.assertions.assertEqual(
      patch.git_fetch_url,
      'https://chromium-review.googlesource.com/chromium/src')
  api.assertions.assertEqual(patch.git_fetch_ref, 'refs/changes/27/91827/1')

  # Missing result
  with api.assertions.assertRaises(api.step.StepFailure):
    api.gerrit.fetch_patch_sets(CHANGES, test_output_data={'changes': [{}]})

  # Missing result
  with api.step.nest('test fetch_patch_sets_from_change missing'):
    # Fetch for wrong patchset. Should raise an error.
    change = GerritChange(host='google.com', change=2, patchset=4)
    with api.assertions.assertRaises(api.step.StepFailure):
      api.gerrit.fetch_patch_set_from_change(change)

  test_response = {
      'changes': [{
          'host': 'https://chromium-review.googlesource.com',
          'change_number': 12345,
          'patch_set': 1,
          'info': {
              '_number': 12345,
          },
          'patch_set_revision': 'f000' * 10,
          'revision_info': {
              '_number': 1,
          },
      }]
  }
  patch_sets = api.gerrit.fetch_patch_sets(CHANGES,
                                           test_output_data=test_response)
  patch_set = patch_sets[0]
  # Missing commit info
  with api.step.nest('test fetch_patch_sets without commit_info'):
    with api.assertions.assertRaises(InfraFailure):
      _ = patch_set.commit_info


# Missing detailed labels
  with api.step.nest('test fetch_patch_sets without detailed labels'):
    with api.assertions.assertRaises(InfraFailure):
      _ = patch_set.has_label_vote('Code-Review', -1)
    with api.assertions.assertRaises(InfraFailure):
      _ = patch_set.has_default_label_vote('Commit-Queue')

  api.gerrit.test_api.test_patch_set()


def GenTests(api):
  yield api.test(
      'basic',
      api.gerrit.set_gerrit_fetch_changes_response('test fetch_patch_sets',
                                                   CHANGES,
                                                   _get_values_dict(api)),
      api.gerrit.set_gerrit_fetch_changes_response(
          'test fetch_patch_sets_from_change', CHANGES, _get_values_dict(api)),
      api.gerrit.set_gerrit_fetch_changes_response(
          'test fetch_patch_sets_from_change missing', CHANGES,
          _get_values_dict(api)),
  )
