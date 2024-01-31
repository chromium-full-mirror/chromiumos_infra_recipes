# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.git.examples.fetch_refs import FetchProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'git',
]


PROPERTIES = FetchProperties


def RunSteps(api, properties):
  snapshot = properties.snapshot
  shas = api.git.fetch_refs(
      'https://{}/{}'.format(snapshot.host, snapshot.project), snapshot.ref,
      count=properties.count)
  api.assertions.assertEqual(properties.expected_shas, shas)


def GenTests(api):

  def test(name, sha='deadbeefdeaddeadbeefdeadbeefdeaddeadbeef', count=1,
           expected_shas=None):
    if expected_shas is None:
      expected_shas = [sha] + api.git.generate_test_ids(count - 1)
    ret = api.test(
        name,
        api.properties(
            FetchProperties(
                snapshot=GitilesCommit(host='chrome-internal.googlesource.com',
                                       project='chromeos/manifest-internal',
                                       ref='refs/heads/snapshot', id=sha),
                count=count, expected_shas=expected_shas or [])))
    if len(expected_shas) == count:
      ret += api.step_data(
          'git log',
          stdout=api.raw_io.output_text('\n'.join(expected_shas) + '\n'))
    else:
      ret += api.step_data('git log', retcode=1)
      for idx, val in enumerate(expected_shas, start=1):
        step_name = 'git rev-parse' if idx == 1 else 'git rev-parse (%d)' % idx
        ret += api.step_data(step_name,
                             stdout=api.raw_io.output_text('%s\n' % val))
        if count != len(expected_shas):
          ret += api.step_data('git rev-parse (%d)' % (len(expected_shas) + 1),
                               retcode=1)
    return ret

  yield test('basic',)

  yield test('multi', count=2)

  yield test(
      'partial', count=4, expected_shas=[
          'fee26543c80f67cb9cee4b1ff6c8416c6aa0a271',
          'c4f2fb13b32ac33eb6a9d6a4bf0dad7c0bfaab20',
      ])
