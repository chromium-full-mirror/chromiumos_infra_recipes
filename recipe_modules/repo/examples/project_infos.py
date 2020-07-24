# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'repo',
]

from PB.recipe_modules.chromeos.repo.examples.project_infos import (
    ProjectInfo, ProjectInfosProperties)

PROPERTIES = ProjectInfosProperties


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  # Special case: If we have one project and no regexes, we can call
  # api.repo.project_info() instead of project_infos().
  if len(properties.projects) == 1 and not properties.regexes:
    infos = [api.repo.project_info(properties.projects[0])]
  else:
    infos = api.repo.project_infos(
        projects=list(properties.projects), regexes=list(properties.regexes))

  if not properties.expected_infos:
    expected = [
        api.repo.ProjectInfo(name=x, path='src/{}'.format(x), remote='cros',
                             branch='refs/heads/master') for x in 'a', 'b', 'c'
    ]
  else:
    expected = [
        api.repo.ProjectInfo(x.name, x.path, x.remote, x.branch)
        for x in properties.expected_infos
    ]

  api.assertions.assertEqual(expected, infos)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'one-project',
      api.properties(
          ProjectInfosProperties(
              projects=['galaxy'], expected_infos=[
                  ProjectInfo(name='galaxy', path='src/galaxy', remote='cros',
                              branch='refs/heads/master')
              ])))

  yield api.test(
      'two-projects',
      api.properties(
          ProjectInfosProperties(
              projects=['galaxy', 'other'], expected_infos=[
                  ProjectInfo(name='galaxy', path='src/galaxy', remote='cros',
                              branch='refs/heads/master'),
                  ProjectInfo(name='other', path='src/other', remote='cros',
                              branch='refs/heads/master')
              ])))

  yield api.test(
      'regexes',
      api.properties(
          ProjectInfosProperties(
              regexes=['src/program/galaxy', 'src/program/other'])))

  missing_refs_heads = '\n'.join(
      '%s|src/%s|cros|refs/heads/master|' % (p, p) for p in ['a', 'b', 'c'])
  yield api.test(
      'no-upstream-attribute',
      api.step_data('repo forall',
                    stdout=api.raw_io.output(missing_refs_heads)))
