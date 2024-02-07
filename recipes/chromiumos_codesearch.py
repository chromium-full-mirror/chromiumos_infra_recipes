# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for enabling cross-references in code search for ChromiumOS.

Checks out and builds ChromiumOS for amd64-generic, does some preprocessing for
package_index, and generates then uploads a KZIP to GS.
"""

from PB.chromite.api import sysroot as sysroot_pb2
from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipes.chromeos.chromiumos_codesearch import (
    ChromiumosCodesearchProperties)
from recipe_engine import post_process
from recipe_engine import recipe_api

DEPS = [
    'infra/codesearch',
    'depot_tools/bot_update',
    'depot_tools/gclient',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'easy',
]

PROPERTIES = ChromiumosCodesearchProperties


def RunSteps(api, properties):

  # Shorthand common variables.
  codesearch_mirror_revision = properties.codesearch_mirror_revision
  codesearch_mirror_revision_timestamp = properties.codesearch_mirror_revision_timestamp
  manifest_hash = properties.manifest_hash
  build_target = api.build_menu.build_target.name
  corpus = properties.corpus
  packages = properties.packages
  sync_generated_files = properties.sync_generated_files
  experimental = properties.experimental

  # Get infra/infra.
  cache_dir = api.path['cache'].join('builder')
  api.gclient.set_config('infra_superproject')

  # The codesearch recipe module relies on checkout path to be set.
  chromiumos_src_dir = api.cros_source.workspace_path.join('src')
  api.path['checkout'] = chromiumos_src_dir

  commit = GitilesCommit(host='chromium.googlesource.com', id=manifest_hash,
                         ref='refs/heads/snapshot',
                         project='chromiumos/manifest')

  # Set up and build ChromiumOS.
  with api.build_menu.configure_builder(commit=commit) as config, \
      api.build_menu.setup_workspace_and_chroot(replace=True):

    config.build.use_flags.append(
        common_pb2.UseFlag(flag='compilation_database'))

    env_info = api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config=config, packages=env_info.packages,
                                    timeout_sec=60 * 60 * 12)

    # Once ChromiumOS has been set up, start the process of creating a kzip.
    workspace = api.cros_source.workspace_path
    with api.context(cwd=workspace):
      # package_index_cros requires chromite/ in a parent directory.
      chromite_contrib = workspace.join('chromite', 'contrib')
      package_index_cros_dir = chromite_contrib.join('package_index_cros')

      # Generate KZIP.
      build_dir = workspace.join('src', 'out', build_target)
      with api.context(
          cwd=package_index_cros_dir, env={
              'PATH':
                  api.path.pathsep.join(
                      [str(workspace.join('chromite', 'bin')), '%(PATH)s'])
          }):
        api.step('run package_index_cros', [
            package_index_cros_dir.join('main'),
            '--debug',
            '--board',
            build_target,
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
          PLATFORM=build_target,
          EXPERIMENTAL=experimental,
          SYNC_GENERATED_FILES=sync_generated_files,
          CORPUS=corpus,
      )

      # Download chromium clang tools.
      clang_dir = api.codesearch.clone_clang_tools(cache_dir)

      # Run the translation_unit tool in chromiumos/src dirs.
      target_architecture = _get_target_architecture(api, build_target)
      api.codesearch.run_clang_tool(
          clang_dir=clang_dir, run_dirs=[
              chromiumos_src_dir.join('platform2'),
          ], target_architecture=target_architecture)

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
          # ~/chromiumos/src/out/${build_target};src/out/${build_target}
          build_dir: api.path.join('src', 'out', build_target),

          # ~/cros_chroot/chroot;chroot
          api.build_menu.chroot.path: 'chroot',

          # ~/cros_chroot/out;out
          api.build_menu.chroot.out_path: 'out',
      }

      # Don't sync chroot/home/ nor out/home. The directory doesn't contain any
      # relevant files for cross-references.
      ignore = (
          api.path.join(api.build_menu.chroot.path, 'home'),
          api.path.join(api.build_menu.chroot.out_path, 'home'),
      )

      api.codesearch.checkout_generated_files_repo_and_sync(
          copy_config, kzip_path=kzip_path, ignore=ignore,
          revision=codesearch_mirror_revision)


def _get_target_architecture(api: recipe_api.RecipeApi,
                             build_target: str) -> str:
  """Return the given build target's architecture, such as "amd64"."""
  request = sysroot_pb2.GetTargetArchitectureRequest(
      build_target=common_pb2.BuildTarget(name=build_target),
      chroot=api.cros_sdk.chroot,
  )
  response = api.cros_build_api.SysrootService.GetTargetArchitecture(request)
  return response.architecture


# TODO(crbug/1284439): Add more tests.
def GenTests(api):
  yield api.build_menu.test(
      'basic',
      api.buildbucket.generic_build(builder='amd64-generic-codesearch'),
      api.properties(
          codesearch_mirror_revision='a' * 40,
          codesearch_mirror_revision_timestamp='1531887759',
          manifest_hash='d3adb33f',
          corpus='chromium.googlesource.com/chromiumos/codesearch//main',
          packages=[
              'virtual/target-chromium-os', 'virtual/target-chromiumos-test'
          ],
          sync_generated_files=True,
          experimental=False,
      ),
      api.post_check(post_process.StepCommandContains,
                     'run translation_unit clang tool',
                     ['--tool-arg', '-arch', '--tool-arg', 'amd64']))

  yield api.build_menu.test(
      'repo sync to manifest_hash',
      api.buildbucket.generic_build(builder='amd64-generic-codesearch'),
      api.properties(
          codesearch_mirror_revision='a' * 40,
          codesearch_mirror_revision_timestamp='1531887759',
          manifest_hash='d3adb33f',
          corpus='chromium.googlesource.com/chromiumos/codesearch//main',
          packages=[
              'virtual/target-chromium-os', 'virtual/target-chromiumos-test'
          ],
          sync_generated_files=True,
          experimental=False,
      ),
      api.post_process(
          post_process.PropertyEquals, 'commit', '''{
  "host": "chromium.googlesource.com",
  "project": "chromiumos/manifest",
  "id": "d3adb33f",
  "ref": "refs/heads/snapshot"
}'''),
  )
