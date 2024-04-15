# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.repo.examples.project_infos import ProjectInfo
from PB.recipe_modules.chromeos.repo.examples.project_infos import ProjectInfosProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'repo',
    'src_state',
]


PROPERTIES = ProjectInfosProperties


def RunSteps(api, properties):
  repo_root = api.path.start_dir.join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  # Special case: If we have one project and no regexes, we can call
  # api.repo.project_info() instead of project_infos().
  if len(properties.projects) == 1 and not properties.regexes:
    infos = [api.repo.project_info(properties.projects[0])]
    api.assertions.assertTrue(api.repo.project_exists(properties.projects[0]))
    api.assertions.assertFalse(api.repo.project_exists('foo/bar'))
  else:
    infos = api.repo.project_infos(
        projects=list(properties.projects), regexes=list(properties.regexes))

  if not properties.expected_infos:
    expected = [
        api.repo.ProjectInfo(name=x, path='src/{}'.format(x), remote='cros',
                             branch=api.src_state.default_ref,
                             rrev=api.src_state.default_ref)
        for x in api.repo.test_api.test_projects
    ]
  else:
    expected = [
        api.repo.ProjectInfo(x.name, x.path, x.remote, x.branch, x.rrev)
        for x in properties.expected_infos
    ]

  api.assertions.assertEqual(expected, infos)

  api.assertions.assertEqual(
      any(x.branch == x.rrev for x in expected),
      bool(api.repo.ensure_pinned_manifest()))

  info = api.repo.ProjectInfo(name='name', path='path', remote='cros',
                              branch='refs/heads/main', rrev='refs/heads/main')
  api.assertions.assertEqual('main', info.branch_name)

  info = api.repo.ProjectInfo(name='name', path='path', remote='cros',
                              branch='refs/tags/tag', rrev='1' * 40)
  api.assertions.assertEqual('refs/tags/tag', info.branch_name)


def GenTests(api):
  yield api.test('basic')

  yield api.test('passing info', api.repo.project_infos_step_data())

  yield api.test(
      'one-project',
      api.properties(
          ProjectInfosProperties(
              projects=['galaxy'], expected_infos=[
                  ProjectInfo(name='galaxy', path='src/galaxy', remote='cros',
                              branch=api.src_state.default_ref,
                              rrev=api.src_state.default_ref)
              ])),
      api.step_data('check if project foo/bar exists.repo info',
                    stderr=api.raw_io.output_text('project foo/bar not found')),
  )

  test_hash = '0123456789ABCDEFabcdef555555555555555555'
  with_hash = 'galaxy|src/galaxy|cros|%s|%s' % (test_hash,
                                                api.src_state.default_ref)

  yield api.test(
      'snapshot',
      api.step_data('repo forall', stdout=api.raw_io.output_text(with_hash)),
      api.step_data('ensure manifest is pinned.repo forall',
                    stdout=api.raw_io.output_text(with_hash)),
      api.properties(
          ProjectInfosProperties(
              projects=['galaxy'], expected_infos=[
                  ProjectInfo(name='galaxy', path='src/galaxy', remote='cros',
                              branch=api.src_state.default_ref, rrev=test_hash),
              ])),
      api.step_data('check if project foo/bar exists.repo info',
                    stderr=api.raw_io.output_text('project foo/bar not found')),
  )

  yield api.test(
      'two-projects',
      api.properties(
          ProjectInfosProperties(
              projects=['galaxy', 'other'], expected_infos=[
                  ProjectInfo(name='galaxy', path='src/galaxy', remote='cros',
                              branch=api.src_state.default_ref,
                              rrev=api.src_state.default_ref),
                  ProjectInfo(name='other', path='src/other', remote='cros',
                              branch=api.src_state.default_ref,
                              rrev=api.src_state.default_ref)
              ])))

  yield api.test(
      'regexes',
      api.properties(
          ProjectInfosProperties(
              regexes=['src/program/galaxy', 'src/program/other'])))

  missing_refs_heads = '\n'.join('%s|src/%s|cros|%s|' %
                                 (p, p, api.src_state.default_ref)
                                 for p in api.repo.test_projects)
  yield api.test(
      'no-upstream-attribute',
      api.step_data('ensure manifest is pinned.repo forall',
                    stdout=api.raw_io.output_text(missing_refs_heads)),
      api.step_data('repo forall',
                    stdout=api.raw_io.output_text(missing_refs_heads)),
  )
