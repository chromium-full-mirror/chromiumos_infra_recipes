# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'repo',
]


def RunSteps(api):
  with api.context(cwd=api.path['cleanup']):
    api.assertions.assertIsNone(api.repo._find_root())

  with api.context(cwd=api.path['start_dir']):
    api.repo.init('http://manifest_url')
    api.repo.init(
        'http://manifest_url',
        manifest_branch='mybranch',
        reference='/preload/chromeos',
        groups=['group1', 'group2'],
        depth=10,
        repo_url='http://repo_url',
        repo_branch='next',
        local_manifest=api.repo.LocalManifest(
            repo='https://chrome-internal.googlesource.com/testproject1',
            path='local_manifest.xml',
        ),
    )
    api.repo.sync()
    api.repo.sync(force_sync=True, detach=True, current_branch=True, jobs=99,
                  manifest_name='snapshot.xml', no_tags=True,
                  optimized_fetch=True, cache_dir='/tmp/cache',
                  retry_fetches=8)

    api.repo.sync_manifest('<manifest></manifest>')

  infos = api.repo.project_infos()
  api.assertions.assertEqual(len(infos), 3)
  api.assertions.assertEqual(infos[0].path, 'src/a')

  info = api.repo.project_info(project='foo')
  api.assertions.assertEqual(info.name, 'foo')

  api.assertions.assertEqual(api.repo.manifest_snapshot(),
                             "<manifest></manifest>")
  api.assertions.assertEqual(api.repo.manifest_snapshot("some_manifest_file"),
                             "<manifest></manifest>")

  snapshot_a = api.path['start_dir'].join('snapshot_a.xml')
  snapshot_b = api.path['start_dir'].join('snapshot_b.xml')
  with api.context(cwd=api.path['cleanup']):
    api.repo.diff_manifests_informational(snapshot_a, snapshot_b)

  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))
  with api.context(cwd=repo_root.join('subdir')):
    api.repo.diff_manifests_informational(snapshot_a, snapshot_b)

  from_manifest = """
    <manifest>
      <project name="NAME" path="PATH" revision="FROM_REV"/>
      <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
      <project name="DELETED" revision="REV"/>
    </manifest>
  """

  to_manifest = """
    <manifest>
      <project name="NAME" path="PATH" revision="TO_REV"/>
      <project name="NO_CHANGE" revision="NO_CHANGE_REV"/>
    </manifest>
  """

  [diff] = api.repo.diff_manifests(from_manifest, to_manifest)
  api.assertions.assertEqual(diff.name, 'NAME')
  api.assertions.assertEqual(diff.path, 'PATH')
  api.assertions.assertEqual(diff.from_rev, 'FROM_REV')
  api.assertions.assertEqual(diff.to_rev, 'TO_REV')

  api.repo.diff_remote_and_local_manifests('URL', 'REV', '<manifest />')

  api.repo.ensure_synced_checkout(api.path['cleanup'].join('ensure'),
                                  'http://manifest_url')

  api.repo.start('no-projects')
  api.repo.start('with-projects', projects=['project'])


def GenTests(api):
  forall_test_data = '\n'.join('%s|src/%s|cros|refs/heads/master|' % (p, p)
                               for p in ['a', 'b', 'c'])

  yield api.test('setup_repo')

  yield (api.test('no-upstream-attribute') +  #
         api.step_data('repo forall', stdout=api.raw_io.output(forall_test_data)))

  yield (api.test('missing-from-XML') +  #
         api.step_data('diff remote and local manifest.git show', retcode=128))
