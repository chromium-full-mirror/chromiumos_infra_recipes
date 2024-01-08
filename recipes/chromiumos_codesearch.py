# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for enabling cross-references in code search for ChromiumOS.

Checks out and builds ChromiumOS for amd64-generic, does some preprocessing for
package_index, and generates then uploads a KZIP to GS.
"""

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipes.chromeos.chromiumos_codesearch import (
    ChromiumosCodesearchProperties)
from recipe_engine.engine_types import freeze
from recipe_engine.post_process import DropExpectation
from recipe_engine.post_process import PropertyEquals

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'infra/codesearch',
    'chromeos/build_menu',
    'chromeos/cros_source',
    'depot_tools/bot_update',
    'depot_tools/gclient',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
]

# TODO(crbug/1284439): Add build_config.
# TODO(crbug/1317852): Move properties outside of recipe.
SPEC = freeze({
    # The builders have the following parameters:
    # - board: the compile targets.
    # - corpus: Kythe corpus to specify in the kzip.
    # - packages: The platform for which the code is compiled.
    # - sync_generated_files: Whether to sync generated files into a git repo.
    # - experimental: Whether to mark Kythe uploads as experimental.
    'builders': {
        'amd64-generic-codesearch': {
            'board': 'amd64-generic',
            'corpus': 'chromium.googlesource.com/chromiumos/codesearch//main',
            'packages': [
                'virtual/target-chromium-os',
                'virtual/target-chromium-os-dev',
                'virtual/target-chromium-os-factory',
                'virtual/target-chromium-os-factory-shim',
                'virtual/target-chromium-os-test',
            ],
            'sync_generated_files': True,
            'experimental': False,
        },
        'arm64-generic-codesearch': {
            'board': 'arm64-generic',
            'corpus': 'chromium.googlesource.com/chromiumos/codesearch//main',
            'packages': [
                'virtual/target-chromium-os',
                'virtual/target-chromium-os-dev',
                'virtual/target-chromium-os-factory',
                'virtual/target-chromium-os-factory-shim',
                'virtual/target-chromium-os-test',
            ],
            'sync_generated_files': True,
            'experimental': False,
        },
    },
})

PROPERTIES = ChromiumosCodesearchProperties


def RunSteps(api, properties):
  codesearch_mirror_revision = properties.codesearch_mirror_revision
  codesearch_mirror_revision_timestamp = properties.codesearch_mirror_revision_timestamp
  manifest_hash = properties.manifest_hash

  builder = api.buildbucket.build.builder.builder
  bot_config = SPEC.get('builders', {}).get(builder)
  assert bot_config is not None, ('Could not find builder %s in SPEC' % builder)

  board = bot_config.get('board', 'amd64-generic')
  corpus = bot_config.get(
      'corpus', 'chromium.googlesource.com/chromiumos/codesearch//main')
  packages = bot_config.get('packages', ['virtual/target-chromium-os'])
  sync_generated_files = bot_config.get('sync_generated_files', False)
  experimental = bot_config.get('experimental', False)

  # Get infra/infra.
  cache_dir = api.path['cache'].join('builder')
  api.gclient.set_config('infra_superproject')

  # The codesearch recipe module relies on checkout path to be set.
  chromiumos_src_dir = api.cros_source.workspace_path.join('src')
  api.path['checkout'] = chromiumos_src_dir
  with api.context(cwd=cache_dir):
    api.bot_update.ensure_checkout(set_output_commit=False)

  commit = GitilesCommit(host='chromium.googlesource.com', id=manifest_hash,
                         ref='refs/heads/snapshot',
                         project='chromiumos/manifest')

  # Set up and build ChromiumOS.
  # TODO(gavinmak): Fix tests and remove "no cover".
  with api.build_menu.configure_builder(commit=commit) as config, \
      api.build_menu.setup_workspace_and_chroot(replace=True):  # pragma: no cover
    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config=config, packages=env_info.packages,
                                    timeout_sec=60 * 60 * 12)

    # Once ChromiumOS has been set up, start the process of creating a kzip.
    workspace = api.cros_source.workspace_path
    with api.context(cwd=workspace):
      # package_index_cros requires chromite/ in a parent directory.
      chromiumos_scripts_dir = workspace.join('src', 'scripts')
      package_index_cros_dir = chromiumos_scripts_dir.join('package_index_cros')
      api.step('copy package_index_cros to chromiumos/src/scripts', [
          'cp', '-r',
          cache_dir.join('infra', 'go', 'src', 'infra', 'cmd',
                         'package_index_cros'), chromiumos_scripts_dir
      ])

      # This hook causes package_index_cros to fail. See
      # https://crbug.com/1484258#c12.
      hook_path = workspace.join('src', 'scripts', 'hooks', 'install',
                                 'find-missing-deps.sh')
      api.file.remove('remove deps hook', hook_path)

      # Generate KZIP.
      build_dir = workspace.join('src', 'out', board)
      with api.context(
          cwd=chromiumos_scripts_dir, env={
              'PATH':
                  api.path.pathsep.join(
                      [str(workspace.join('chromite', 'bin')), '%(PATH)s'])
          }):
        api.step('run package_index_cros', [
            'python3',
            package_index_cros_dir.join('main.py'),
            '--verbose',
            '--with-tests',
            '--keep-going',
            '--board',
            board,
            '--chroot',
            api.build_menu.chroot.path,
            '--chroot-out',
            api.build_menu.chroot.out_path,
            '--build-dir',
            build_dir,
            '--compile-commands',
            build_dir.join('compile_commands.json'),
        ] + list(packages))

      api.codesearch.set_config(
          'chromiumos',
          PROJECT='chromiumos',
          CHECKOUT_PATH=chromiumos_src_dir,
          PLATFORM=board,
          EXPERIMENTAL=experimental,
          SYNC_GENERATED_FILES=sync_generated_files,
          CORPUS=corpus,
      )

      # Download chromium clang tools.
      clang_dir = api.codesearch.clone_clang_tools(cache_dir)

      # Run the translation_unit tool in chromiumos/src dirs.
      api.codesearch.run_clang_tool(
          clang_dir=clang_dir, run_dirs=[
              chromiumos_src_dir.join('platform2'),
              chromiumos_src_dir.join('aosp', 'system', 'update_engine'),
          ])

      # Create the kythe index pack and upload it to google storage.

      # package_index needs a gn_targets.json file. Since we don't use one for
      # chromiumos codesearch, write an empty json file.
      # TODO(gavinmak): Make gn_targets optional in package_index.
      api.file.write_json('write empty gn_targets.json file',
                          build_dir.join('gn_targets.json'), {})
      kzip_path = api.codesearch.create_and_upload_kythe_index_pack(
          commit_hash=codesearch_mirror_revision,
          commit_timestamp=int(codesearch_mirror_revision_timestamp or
                               api.time.time()))

      # Check out the generated files repo and sync the generated files
      # into this checkout.
      copy_config = {
          # ~/chromiumos/src/out/${board};src/out/${board}
          build_dir: api.path.join('src', 'out', board),

          # ~/cros_chroot/chroot;chroot
          api.build_menu.chroot.path: 'chroot',

          # ~/cros_chroot/out;out
          api.build_menu.chroot.out_path: 'out',
      }

      # Don't sync chroot/home/. The directory doesn't contain any relevant
      # files for cross-references.
      ignore = (api.path.join(api.build_menu.chroot.path, 'home'),)

      api.codesearch.checkout_generated_files_repo_and_sync(
          copy_config, kzip_path=kzip_path, ignore=ignore,
          revision=codesearch_mirror_revision)


# TODO(crbug/1284439): Add more tests.
def GenTests(api):
  for b in ('amd64', 'arm64'):
    yield api.test(
        'basic_%s' % b,
        api.buildbucket.generic_build(builder='%s-generic-codesearch' % b),
        api.properties(codesearch_mirror_revision='a' * 40,
                       codesearch_mirror_revision_timestamp='1531887759',
                       manifest_hash='d3adb33f'),
        # TODO (b/275363240): audit this test.
        status='FAILURE',
    )

  yield api.test(
      'repo sync to manifest_hash',
      api.buildbucket.generic_build(builder='amd64-generic-codesearch'),
      api.properties(codesearch_mirror_revision='a' * 40,
                     codesearch_mirror_revision_timestamp='1531887759',
                     manifest_hash='d3adb33f'),
      api.post_process(
          PropertyEquals, 'commit', '''{
  "host": "chromium.googlesource.com",
  "project": "chromiumos/manifest",
  "id": "d3adb33f",
  "ref": "refs/heads/snapshot"
}'''),
      api.post_process(DropExpectation),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )
