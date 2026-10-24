"""Trusted package controls, admission ordering and CAS-fresh graph regressions."""
import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ci import dispatch, repository
from ci.publish import apt, publication, openwrt, rpm
from support import CoordinatorCase, PinnedJsonCase, feed_manifest, ipk
import test_cascade_admission as cascade_admission
import test_corrective_revision2 as corrections


class TrustedControlsTest(PinnedJsonCase):
    def fixture(self, base, distro='openwrt', retained=False, name='snodec', release=None, arch=None, target=None):
        target = target or {'openwrt':'openwrt-24.10-x86_64','apk':'openwrt-25.12-x86_64',
                  'debian':'debian-trixie-amd64','rocky':'rocky-9-x86_64'}[distro]
        row = next(r for r in publication.targets() if r['id'] == target)
        root, bundle, incoming = (base / n for n in ['feed', 'bundle', 'incoming'])
        root.mkdir()
        graph = copy.deepcopy(repository.PROJECTS)
        sources = {'snode.c': {'refs/tags/v1.0.0': 'a' * 40}}
        context = dict(build_project='snode.c', release_project='snode.c', cause='release',
                       source_tags={'snode.c': 'v1.0.0'}, versions={'snode.c': '1.0.0'})
        folder = (Path('openwrt')/row['suite']/row['arch'] if row['family'] == 'openwrt'
                  else Path('linux')/row['distribution']/row['suite']/row['arch'])
        directory = incoming / folder
        directory.mkdir(parents=True)
        extension = 'rpm' if distro == 'rocky' else 'apk' if distro == 'apk' else 'ipk' if distro == 'openwrt' else 'deb'
        expected = repository.package_version(row, '1.0.0', '2')
        package = directory / ('Packages' if extension == 'rpm' else '') / ('snodec_' + expected + '.' + extension)
        package.parent.mkdir(exist_ok=True)
        def make(path, internal, version):
            if extension == 'ipk':
                ipk(path, internal, version, arch or row['arch'])
            elif extension == 'apk':
                path.write_text(json.dumps(dict(info=dict(name=internal,version=version,arch=arch or row['arch']))))
            elif extension == 'rpm':
                build = Path(tempfile.mkdtemp(prefix='rpm-build-',dir=base))
                (build/'tmp').mkdir()
                upstream, revision = version.split('-',1)
                spec = build/'fixture.spec'
                spec.write_text(f'Name: {internal}\nVersion: {upstream}\nRelease: {revision}\nSummary: controls fixture\n'
                    f'License: MIT\nBuildArch: {arch or row["arch"]}\n%description\nFixture.\n'
                    '%install\nmkdir -p %{buildroot}/usr/share/fixture\nprintf fixture > %{buildroot}/usr/share/fixture/data\n'
                    '%files\n/usr/share/fixture/data\n')
                repository.run('rpmbuild','--define',f'_topdir {build}','--define',f'_tmppath {build/"tmp"}',
                               '--define',f'_dbpath {build/"rpmdb"}','-bb',str(spec),stderr=subprocess.DEVNULL)
                shutil.move(str(next((build/'RPMS').rglob('*.rpm'))),path)
            else:
                staging = path.parent / ('staging-' + path.stem)
                (staging / 'DEBIAN').mkdir(parents=True)
                (staging / 'DEBIAN/control').write_text(
                    f'Package: {internal}\nVersion: {version}\nArchitecture: {arch or row["arch"]}\n'
                    'Maintainer: Fixture <fixture@example.invalid>\nDescription: controls fixture\n')
                repository.run('dpkg-deb', '--build', '--root-owner-group', str(staging), str(path))
                shutil.rmtree(staging)
            return None
        make(package, name, release or expected)
        current = {}
        if retained:
            source = {'mqttsuite': {'refs/tags/v1.0.0': 'b' * 40}}
            previous_name = 'mqttsuite_' + repository.package_version(row, '1.0.0', '1') + '.' + extension
            if extension == 'rpm':
                previous_name = 'Packages/'+previous_name
            previous = (root / publication.feed_paths(row)[0] / previous_name if row['family'] == 'openwrt' or extension == 'rpm'
                        else root / 'debian/pool/trixie' / previous_name)
            previous.parent.mkdir(parents=True, exist_ok=True)
            make(previous, 'mqttsuite', repository.package_version(row, '1.0.0', '1'))
            current = feed_manifest(dict(sources=source, files={previous_name: repository.digest(previous)},
                versions={'mqttsuite': repository.package_version(row, '1.0.0', '1')}, packages=['mqttsuite']), graph)
            path = root / publication.feed_paths(row)[0]
            path.mkdir(parents=True, exist_ok=True)
            publication.write(path / 'build.json', dict(files={'pool/trixie/' + previous_name: repository.digest(previous)},
                targets={row['arch']: current}) if extension == 'deb' else current)
            if distro == 'openwrt':
                (path / 'Packages').write_text('\n\n')
            sources.update(source)
        files = {str(package.relative_to(directory)): repository.digest(package)}
        if distro == 'openwrt':
            data = (f'Package: {name}\nVersion: {release or expected}\nArchitecture: {arch or row["arch"]}\n'
                    f'Filename: {package.name}\n\n').encode()
            (directory / 'Packages').write_bytes(data)
            (directory / 'Packages.gz').write_bytes(gzip.compress(data))
            files.update({n: repository.digest(directory / n) for n in ['Packages', 'Packages.gz']})
        elif distro == 'apk':
            (directory / 'packages.adb').write_text('synthetic unsigned index')
            files['packages.adb'] = repository.digest(directory / 'packages.adb')
        profile = dict(projects=graph, sources=sources, context=context, baseline=current, archives={'snode.c': 'source.tar.gz'})
        publication.write(bundle / 'profiles.json', {row['id']: profile})
        publication.write(bundle / 'checksums.json', {})
        (bundle / 'archives').mkdir()
        (bundle / 'archives/source.tar.gz').touch()
        metadata = dict(row['build'] if row['family']=='linux' else row, series=row['suite'], revision='2', sources=sources, context=context,
                        versions=current.get('versions', {}) | {'snode.c': expected}, files=files,
                        packages=[] if name != 'snodec' else ['snodec'],
                        architectures=[row['arch']], image=row['build'].get('image'))
        publication.write(directory / 'build.json', metadata)
        generation = dict(context=context, revisions={'snode.c': '2'}, profiles_hash=repository.digest(bundle / 'profiles.json'))
        return root, bundle, incoming, row, generation, directory

    def publish(self, fixture, on_sign=None):
        root, bundle, incoming, row, generation, directory = fixture
        def sign(*args):
            if on_sign:
                on_sign()
            destination = root / publication.feed_paths(row)[0]
            shutil.copytree(directory, destination, dirs_exist_ok=True)
            return None
        def index(base, suite, targets):
            (base / 'dists' / suite).mkdir(parents=True, exist_ok=True)
            return None
        with patch.object(repository, 'activate'), patch.object(publication, 'activate'), \
                patch.object(repository, 'publish', side_effect=sign), patch.object(apt, 'index', side_effect=index), \
                patch('ci.publish.cleanup.cleanup'):
            publication.publish(root, bundle, incoming, row, generation, 'snode.c')
        return None

    def test_realistic_index_manifest_survives_and_retained_empty_index_heals(self):
        for retained in [False, True]:
            with self.subTest(retained=retained), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture(Path(temporary), retained=retained)
                self.publish(fixture)
                root, _, _, row, _, _ = fixture
                directory = root / publication.feed_paths(row)[0]
                text = (directory / 'Packages').read_text()
                self.assertEqual(text.count('Package: snodec\n'), 1)
                self.assertEqual(text.count('Package: mqttsuite\n'), int(retained))
                self.assertEqual(gzip.decompress((directory / 'Packages.gz').read_bytes()).decode(), text)
                manifest = publication.read(directory / 'build.json')
                for name, checksum in manifest['files'].items():
                    self.assertEqual(repository.digest(directory / name), checksum)
        return None

    def test_artifact_filename_cannot_inject_an_index_paragraph(self):
        suffixes = ['\n\nPackage: mqttsuite\nVersion: 9-r9\nArchitecture: x86_64\nFilename: foreign.ipk',
                    '\rFilename: foreign.ipk', '\tforeign.ipk']
        for retained in [False, True]:
            for suffix in suffixes:
                with self.subTest(retained=retained, suffix=repr(suffix)), tempfile.TemporaryDirectory() as temporary:
                    fixture = self.fixture(Path(temporary), retained=True)
                    root, _, _, row, _, directory = fixture
                    destination = root / publication.feed_paths(row)[0] if retained else directory
                    project = 'mqttsuite' if retained else 'snodec'
                    package = next(destination.glob(project + '_*.ipk'))
                    name = package.name + suffix
                    package.rename(destination / name)
                    metadata = publication.read(destination / 'build.json')
                    entries = [metadata, metadata['releases']['mqttsuite']['v1.0.0']] if retained else [metadata]
                    for entry in entries:
                        entry['files'][name] = entry['files'].pop(package.name)
                    publication.write(destination / 'build.json', metadata)
                    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    sign = unittest.mock.Mock()
                    with self.assertRaisesRegex(ValueError, 'filename'):
                        self.publish(fixture, on_sign=sign)
                    sign.assert_not_called()
                    self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary), name='snodec-folded\n mqttsuite')
            root = fixture[0]
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError, 'filename') as error:
                self.publish(fixture)
            self.assertNotIn('\n', str(error.exception))
            self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        return None

    def test_ipk_control_cannot_inject_an_unvalidated_index_paragraph(self):
        import io
        import tarfile
        for suffix in ['\nPackage: mqttsuite\nVersion: 9-r9\nArchitecture: x86_64\n',
                       'invalid control line\nPackage: mqttsuite\n']:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture(Path(temporary), retained=True)
                root, _, _, _, _, directory = fixture
                package = next(directory.glob('snodec_*.ipk'))
                fields = repository.package_metadata(package)
                control = fields['control'] + suffix
                inner = io.BytesIO()
                with tarfile.open(fileobj=inner, mode='w:gz') as archive:
                    member = tarfile.TarInfo('./control')
                    member.size = len(control.encode())
                    archive.addfile(member, io.BytesIO(control.encode()))
                with tarfile.open(package, mode='w:gz') as archive:
                    member = tarfile.TarInfo('./control.tar.gz')
                    member.size = len(inner.getvalue())
                    archive.addfile(member, io.BytesIO(inner.getvalue()))
                metadata = publication.read(directory/'build.json')
                metadata['files'][package.name] = repository.digest(package)
                publication.write(directory/'build.json', metadata)
                before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaisesRegex(ValueError, 'control paragraph'):
                    self.publish(fixture)
                self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        return None

    def overlap_fixture(self, base):
        fixture = self.fixture(base)
        root, _, _, row, _, _ = fixture
        destination = root/publication.feed_paths(row)[0]
        destination.mkdir(parents=True)
        files = {}
        for project, prefix in [('snode.c','snodec'),('mqttsuite','snodec-foreign')]:
            filename = prefix+'_1.0.0-r1_x86_64.ipk'
            ipk(destination/filename, prefix, '1.0.0-r1')
            files[filename] = repository.digest(destination/filename)
        current = feed_manifest(dict(sources={'snode.c':{'refs/tags/v1.0.0':'c'*40},
            'mqttsuite':{'refs/tags/v1.0.0':'b'*40}}, files=files,
            versions={'snode.c':'1.0.0-r1','mqttsuite':'1.0.0-r1'},packages=['snodec','snodec-foreign']))
        publication.write(destination/'build.json', current)
        return fixture, current

    def test_omitted_or_poisoned_sibling_facts_cannot_publish_foreign_files(self):
        for poison in [False, True]:
            for sdk in [False, True]:
                with self.subTest(poison=poison,sdk=sdk), tempfile.TemporaryDirectory() as temporary, \
                        patch.dict(repository.PROJECTS['mqttsuite'], package='snodec-foreign'):
                    repository.definition_data.cache_clear()
                    fixture, current = self.overlap_fixture(Path(temporary))
                    root, _, _, row, _, directory = fixture
                    metadata = publication.read(directory/'build.json')
                    filename = ('snodec-foreign-openwrt-build-deps-1.0.0-r2.tar.zst' if sdk
                                else 'snodec-foreign_1.0.0-r2_x86_64.ipk')
                    if sdk:
                        (directory/filename).write_bytes(b'unused foreign SDK input')
                    else:
                        ipk(directory/filename, 'snodec-foreign', '1.0.0-r2')
                    metadata['files'][filename] = repository.digest(directory/filename)
                    if poison:
                        metadata['sources']['mqttsuite'] = {'refs/tags/v1.0.0':'d'*40}
                    publication.write(directory/'build.json', metadata)
                    original = repository.content
                    def content(project, path, commit):
                        data = json.loads(original(project,path,commit))
                        if project == 'mqttsuite' and commit == 'd'*40:
                            data['package'] = 'previous-foreign'
                        return json.dumps(data).encode()
                    with patch.object(repository,'content',side_effect=content):
                        self.publish(fixture)
                    self.assertFalse(any(args[0]=='mqttsuite' and args[2]=='d'*40
                                         for args, _ in original.call_args_list))
                    destination = root/publication.feed_paths(row)[0]
                    self.assertFalse((destination/filename).exists())
                    result = publication.read(destination/'build.json')
                    self.assertEqual(result['releases']['mqttsuite'],current['releases']['mqttsuite'])
                    self.assertIn('Filename: snodec_1.0.0-r2.ipk',(destination/'Packages').read_text())
                    self.assertNotIn('Filename: '+filename,(destination/'Packages').read_text())
        return None

    def test_retained_package_needs_its_own_expected_version_owner(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
                repository.PROJECTS['mqttsuite'], package='snodec-foreign'):
            fixture, current = self.overlap_fixture(Path(temporary))
            root, _, _, row, _, _ = fixture
            current['releases']['mqttsuite']['v1.0.0']['versions'] = {}
            publication.write(root/publication.feed_paths(row)[0]/'build.json',current)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError,'ownership|pinned release'):
                self.publish(fixture)
            self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()},before)
        return None

    def test_foreign_internal_namespace_rejected_at_publication_for_ipk_and_deb(self):
        for distro in ['openwrt', 'debian']:
            with self.subTest(distro=distro), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture(Path(temporary), distro, retained=True, name='mqttsuite')
                root = fixture[0]
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaisesRegex((ValueError, RuntimeError), 'ownership|namespace|name.*filename'):
                    self.publish(fixture)
                self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)
        return None

    def test_wrong_version_and_architecture_rejected_before_feed_mutation(self):
        for changes in [dict(release='9.0.0-r999'), dict(arch='aarch64_generic')]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture(Path(temporary), **changes)
                with self.assertRaisesRegex((ValueError, RuntimeError), 'version|architecture'):
                    self.publish(fixture)
                self.assertEqual(list(fixture[0].iterdir()), [])
        return None

    def test_unrelated_capture_key_cannot_replace_current_feed_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = self.fixture(base)
            pinned, overlay = base / 'pinned', base / 'overlay'
            for root, apk in [(pinned, 'old apk'), (overlay, 'current apk')]:
                (root / 'keys').mkdir(parents=True)
                (root / 'keys/opkg.pub').write_text('same opkg')
                (root / 'keys/apk.pem').write_text(apk)
            with patch.object(publication, 'ROOT', pinned), patch.dict(os.environ, PACKAGE_SITE=str(overlay / 'site')):
                self.publish(fixture)
            self.assertEqual((fixture[0] / 'keys/apk.pem').read_text(), 'current apk')
        return None

    def test_rotated_family_key_fails_before_any_signing(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = self.fixture(base)
            for folder, value in [('pinned','old'),('overlay','current')]:
                (base/folder/'keys').mkdir(parents=True)
                (base/folder/'keys/opkg.pub').write_text(value)
            signed = []
            with patch.object(publication,'ROOT',base/'pinned'), \
                    patch.dict(os.environ,PACKAGE_SITE=str(base/'overlay/site')), \
                    self.assertRaisesRegex(RuntimeError,'verification key.*authority'):
                self.publish(fixture,lambda: signed.append(True))
            self.assertEqual(list(fixture[0].iterdir()),[])
            self.assertEqual(signed,[])
        return None

    def test_synthetic_apk_tool_controls_reject_foreign_namespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary),'apk',retained=True,name='mqttsuite')
            real_run = repository.run
            def query(*args, **kwargs):
                result = Path(args[-1]).read_text() if args[:3] == ('apk','adbdump','--format') else real_run(*args,**kwargs)
                return result
            def index(*args):
                result = None
                if args[1] == 'mkndx':
                    (fixture[-1]/'packages.adb').write_text('synthetic index')
                else:
                    result = json.dumps(dict(packages=[json.loads(p.read_text())['info'] for p in fixture[-1].glob('*.apk')]))
                return result
            before = {str(p.relative_to(fixture[0])):p.read_bytes() for p in fixture[0].rglob('*') if p.is_file()}
            with patch.object(repository,'run',side_effect=query), patch.object(openwrt,'run',side_effect=index), \
                    self.assertRaisesRegex(ValueError,'ownership'):
                self.publish(fixture)
            self.assertEqual({str(p.relative_to(fixture[0])):p.read_bytes() for p in fixture[0].rglob('*') if p.is_file()},before)
        return None

    def test_apk_index_must_cover_every_verified_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory/'own.apk').write_bytes(b'synthetic payload')
            def index(*args):
                result = None
                if args[1] == 'mkndx':
                    (directory/'packages.adb').write_bytes(b'synthetic index')
                else:
                    result = json.dumps(dict(packages=[]))
                return result
            info = dict(series='25.12',files={'own.apk':repository.digest(directory/'own.apk')})
            with patch.object(openwrt,'run',side_effect=index), self.assertRaisesRegex(ValueError,'exactly cover'):
                openwrt.reindex(directory,info,{'own.apk':dict(name='own',version='1-r1',arch='x86_64')})
        return None

    def test_render_lists_only_distributions_with_recorded_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'docs').mkdir()
            (root/'README.md').write_text('<!-- packages:begin platforms -->\n<!-- packages:end platforms -->')
            config = copy.deepcopy(repository.PROJECTS['snode.c'])
            row = next(r for r in repository.rows(config) if r['id']=='debian-trixie-amd64')
            config['matrix'] = dict(linux=[dict(distribution='debian',suite='trixie',image=row['build']['image'],architectures=['amd64'])])
            config['build'] = {'native':config['build']['native']}
            context = dict(tag='v1.0.0',release_project='snode.c',projects={'snode.c':config})
            generation = dict(run_id='100',context=context,revisions={'snode.c':'1'},targets=[row],
                sources={row['id']:{'snode.c':{'refs/tags/v1.0.0':'a'*40}}},nodes={row['id']+'/snode.c':{'status':'pending'}})
            publication.render(root,dict(runs={'100':generation}))
            text = (root/'README.md').read_text()
            self.assertIn('[Debian]',text)
            self.assertNotIn('[Fedora]',text)
            self.assertNotIn('[Rocky',text)
        return None

    @unittest.skipUnless(all(shutil.which(t) for t in ['rpmbuild','rpmsign','createrepo_c','gpg']), 'RPM signing tools unavailable')
    def test_real_rpm_foreign_control_is_rejected_at_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = self.fixture(base,'rocky',retained=True,name='mqttsuite')
            keys, home = base/'signing/keys', base/'gnupg'
            keys.mkdir(parents=True)
            home.mkdir(mode=0o700)
            repository.run('gpg','--homedir',str(home),'--batch','--pinentry-mode','loopback','--passphrase','',
                           '--quick-generate-key','Disposable RPM <rpm@example.invalid>','rsa2048','sign','1d',stderr=subprocess.DEVNULL)
            private = repository.run('gpg','--homedir',str(home),'--batch','--armor','--export-secret-keys')
            (keys/'apt.asc').write_text(repository.run('gpg','--homedir',str(home),'--batch','--armor','--export'))
            fingerprint = next(l.split(':')[9] for l in repository.run('gpg','--homedir',str(home),
                               '--with-colons','--list-secret-keys').splitlines() if l.startswith('fpr:'))
            root, _, _, row, _, _ = fixture
            previous = next(root.rglob('*.rpm'))
            repository.run('rpmsign','--define',f'_gpg_name {fingerprint}','--define',f'_gpg_path {home}',
                           '--define','_gpgbin /usr/bin/gpg','--define','_gpg_digest_algo sha256','--addsign',str(previous))
            path = root/publication.feed_paths(row)[0]/'build.json'
            current = publication.read(path)
            filename = str(previous.relative_to(path.parent))
            for record in [current,current['releases']['mqttsuite']['v1.0.0']]:
                record['files'][filename] = repository.digest(previous)
            publication.write(path,current)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(publication,'ROOT',keys.parent), patch.object(rpm,'ROOT',keys.parent), \
                    patch.dict(os.environ,APT_SIGNING_KEY=private), self.assertRaisesRegex(ValueError,'ownership'):
                self.publish(fixture)
            self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()},before)
        return None


    def test_recorded_version_comes_from_verified_capture_expectation(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary))
            metadata = publication.read(fixture[-1]/'build.json')
            metadata['versions']['snode.c'] = '99.0.0-r999'
            publication.write(fixture[-1]/'build.json',metadata)
            self.publish(fixture)
            info = publication.read(fixture[0]/publication.feed_paths(fixture[3])[0]/'build.json')
            self.assertEqual(info['releases']['snode.c']['v1.0.0']['versions']['snode.c'],'1.0.0-r2')
            self.assertEqual(info['versions']['snode.c'],'1.0.0-r2')
        return None


    def test_real_debian_wrong_version_is_rejected_before_feed_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.fixture(Path(temporary),'debian',release='9.0.0-999~trixie')
            with self.assertRaisesRegex(ValueError,'version'):
                self.publish(fixture)
            self.assertEqual(list(fixture[0].iterdir()),[])
        return None

    def test_synthetic_apk_wrong_version_and_architecture_are_rejected(self):
        for changes in [dict(release='9.0.0-r999'),dict(arch='aarch64_generic')]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                fixture = self.fixture(Path(temporary),'apk',**changes)
                original = repository.run
                def query(*args,**kwargs):
                    result = Path(args[-1]).read_text() if args[:3]==('apk','adbdump','--format') else original(*args,**kwargs)
                    return result
                with patch.object(repository,'run',side_effect=query), self.assertRaisesRegex(ValueError,'version|architecture'):
                    self.publish(fixture)
                self.assertEqual(list(fixture[0].iterdir()),[])
        return None


class AdmissionReviewTest(CoordinatorCase):
    diamond = cascade_admission.CascadeAdmissionTest.diamond

    def test_stale_direct_join_is_gated_after_conversion(self):
        info = self.diamond()
        self.add_capture('join', '400', revision='3', cause='release')
        old = copy.deepcopy(info)
        old['releases']['snode.c']['v1.0.0']['revision'] = '1'
        required = list(repository.dependencies('join', self.graph))
        node = dict(status='publishing', cause='release', builds=2, publications=0, waiting=False,
                    artifact={'id': 5, 'digest': 'sha256:' + 'a' * 64}, requires=required,
                    dependencies=repository.binding(old, required), source=dict(run=900, attempt=1))
        self.state['runs']['400']['nodes'] = {self.row['id'] + '/join': node}
        self.artifacts['SNodeC/join', 900] = [dict(id=5, expired=False)]
        self.save()
        self.tick()
        after = self.node('join', '400')
        self.assertEqual(after['status'], 'pending', after)
        self.assertFalse(any(json.loads(p['inputs']['request'])['project'] == 'join' for _, p in self.posts))
        self.state = publication.read(self.root/'status.json')
        selected = info['releases']['snode.c-idp'].pop('v1.0.0')
        selected.update(revision='3',sources={'snode.c-idp':{'refs/tags/v2.0.0':'e'*40}},
                        versions={'snode.c-idp':'2.0.0-3~trixie'})
        selected['publications']['snode.c-idp'].update(capture='302',revision='3')
        info['releases']['snode.c-idp']['v2.0.0'] = selected
        info['sources']['snode.c-idp'] = selected['sources']['snode.c-idp']
        info['publications']['snode.c-idp'] = selected['publications']['snode.c-idp']
        info['versions']['snode.c-idp'] = selected['versions']['snode.c-idp']
        self.state['runs']['302']['nodes'][self.row['id']+'/snode.c-idp'].update(
            status='published',dependencies=repository.binding(info,['snode.c']))
        publication.write(self.root/'debian/dists/trixie/build.json',{'targets':{'amd64':info}})
        self.save()
        for _ in range(3):
            self.tick()
        admitted = [json.loads(p['inputs']['request']) for _,p in self.posts
                    if json.loads(p['inputs']['request'])['project']=='join']
        self.assertEqual([(p['kind'],p['capture']) for p in admitted],[('build','400')])
        after = self.node('join','400')
        self.assertEqual((after['builds'],after['publications'],after['cause']),(1,0,'dependent'))
        self.assertEqual(after['dependencies'],repository.binding(info,required))
        self.assertEqual(self.state['runs']['400']['sources'][self.row['id']]['join'],self.sources['join'])
        return None

    def test_terminal_artifacts_keep_all_failure_facts_after_dependency_change(self):
        for overlap, status, category in [(o,s,c) for o in [True,False] for s,c in [
                ('failed','deterministic'),('failed','configuration'),('failed','expiry'),('failed','budget'),
                ('cancelled','deterministic'),('unsatisfiable','blocked')]]:
            with self.subTest(overlap=overlap,status=status,category=category), \
                    patch.dict(dispatch.CONFIG['settings'],rebuild_overlap=overlap):
                self.posts.clear()
                info = corrections.CorrectiveRevision2Test.application_fixture(self, dict(status=status, category=category,
                    reason='Original terminal outcome', builds=3, publications=3, attempt=1,
                    artifact={'id': 5, 'digest': 'sha256:' + 'a' * 64}))
                before = copy.deepcopy(self.node('mqttsuite'))
                info['releases']['snode.c']['v1.0.0']['files']['snodec_1_amd64.deb'] = '3' * 64
                publication.write(self.root / 'debian/dists/trixie/build.json', {'targets': {'amd64': info}})
                self.save()
                self.tick()
                self.assertEqual(self.node('mqttsuite'), before)
                self.assertEqual(self.posts, [])
        return None

    def test_rejected_callback_still_runs_reconciliation_and_fails(self):
        request = dict(capture='100')
        self.artifacts[dispatch.COORDINATOR, 100] = [dict(name='source-pair', expired=False)]
        original = dispatch.run
        def run(*args, **kwargs):
            result = ''
            if args[:3] == ('gh', 'run', 'download'):
                shutil.copytree(self.bundle, Path(args[args.index('-D') + 1]), dirs_exist_ok=True)
            else:
                result = original(*args, **kwargs)
            return result
        with patch.dict(os.environ, PACKAGE_REPORT=json.dumps(request), PACKAGE_RETRY='', GITHUB_EVENT_NAME='workflow_dispatch'), \
                patch.object(sys, 'argv', ['dispatch', 'control', str(self.root)]), \
                patch.object(dispatch, 'run', side_effect=run), \
                patch.object(dispatch, 'apply_report', side_effect=ValueError('Forged report')), \
                patch.object(dispatch, 'tick', return_value=False) as tick:
            with self.assertRaisesRegex(ValueError, 'Forged report'):
                dispatch.main()
        tick.assert_called_once()
        return None

    def test_cas_reserve_rejects_concurrent_individually_valid_namespace_collision(self):
        self.concurrent_requests('namespace')
        return None

    def test_cas_reserve_rejects_concurrent_individually_valid_cycle(self):
        self.concurrent_requests('cycle')
        return None

    def concurrent_requests(self, kind, tag='v2.0.0'):
        if kind == 'cycle':
            self.state['requests']['mqttsuite']['v1.0.0']['definition']['depends_on'] = []
            self.save()
        definitions = []
        for project in ['snode.c', 'mqttsuite']:
            graph = copy.deepcopy(self.graph)
            if kind == 'namespace':
                graph[project]['package'] = 'collision'
            else:
                graph[project]['depends_on'] = ['mqttsuite' if project=='snode.c' else 'snode.c']
            graph[project]['_commit'] = ('d' if project=='snode.c' else 'e')*40
            path = self.base / (project + '-definitions.json')
            claimed = {k:v for k,v in graph[project].items() if not k.startswith('_')}
            with patch.object(repository,'DEFINITIONS',path), patch.dict(repository.ROW_PROJECTS,{},clear=True), \
                    patch.object(repository,'definition',return_value=graph[project]):
                repository.configure(self.root,project,graph[project]['_commit'],claimed)
            definitions.append((project,path,graph[project]['_commit']))
        for index, (project,path,sha) in enumerate(definitions):
            env = dict(CI_DEFINITIONS=str(path), RELEASE_PROJECT=project, GITHUB_RUN_ID=str(700 + index),
                RELEASE_TAG=tag, RELEASE_SHA=sha,
                RELEASE_REQUESTED_AT='2026-10-22T00:00:00Z', RELEASE_RUN=str(600 + index), RELEASE_PARENT='',
                GITHUB_WORKFLOW_REF=dispatch.COORDINATOR + '/.github/workflows/orchestrate-packages.yml@refs/heads/main')
            before = self.git('show', 'main:status.json', cwd=self.remote)
            with patch.dict(os.environ, env):
                if index:
                    with self.assertRaises(subprocess.CalledProcessError):
                        repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'reserve')
                    self.assertEqual(self.git('show', 'main:status.json', cwd=self.remote), before)
                else:
                    repository.run('bash', str(repository.ROOT / 'ci/publish/status.sh'), str(self.root), 'reserve')
        return None

    def test_registered_child_is_admitted_while_parent_run_aggregation_lags(self):
        self.feed(['snode.c'])
        self.tick()
        held = copy.deepcopy(self.node('mqttsuite'))
        capture = str(held['source']['run'])
        self.add_capture('mqttsuite',capture,revision='3',cause='dependent',cascade='100')
        self.runs[dispatch.COORDINATOR,int(capture)].update(status='in_progress')
        self.jobs[dispatch.COORDINATOR,int(capture)][0].update(status='completed',conclusion='success')
        self.tick()
        parent = self.node('mqttsuite')
        child = self.node('mqttsuite',capture)
        self.assertEqual(parent['status'],'running')
        self.assertFalse(parent['waiting'])
        self.assertEqual(parent['builds'],held['builds'])
        self.assertEqual(child['request']['kind'],'build')
        self.assertTrue(child['waiting'])
        self.assertEqual(len([p for _,p in self.posts if json.loads(p['inputs']['request']).get('capture')==capture]),1)
        return None

    def test_unobservable_request_is_preserved_and_new_tag_event_replaces_it(self):
        request = dict(definition=self.graph['snode.c'],capture='999',sha='a'*40,tag='v1.0.0',
                       at='2026-10-22T00:00:00Z',run='900',revision='3',eligible=True)
        self.state['requests']['snode.c']['v1.0.0'] = copy.deepcopy(request)
        self.state['counters']['snode.c'] = 3
        self.save()
        original = self.api
        def missing(path,payload=None,token=None):
            if path == f'repos/{dispatch.COORDINATOR}/actions/runs/999':
                raise dispatch.ApiError(404,'Capture unavailable or inaccessible')
            return original(path,payload,token)
        with patch.object(dispatch,'api',side_effect=missing):
            for _ in range(3):
                latest = publication.read(self.root/'status.json')['requests']['snode.c']['v1.0.0']
                now = latest.get('observation',{}).get('retry_at',dispatch.time.time())+1
                with patch.object(dispatch.time,'time',return_value=now):
                    self.tick()
                latest = publication.read(self.root/'status.json')['requests']['snode.c']['v1.0.0']
                self.assertEqual({k:v for k,v in latest.items() if k!='observation'},request)
                self.assertEqual(latest['observation']['category'],'expiry')
        self.assertEqual(self.posts,[])
        graph = copy.deepcopy(self.graph)
        graph['snode.c']['_commit'] = 'd'*40
        path = self.base/'replacement.json'
        publication.write(path,dict(projects=graph))
        with patch.dict(os.environ,CI_DEFINITIONS=str(path),RELEASE_PROJECT='snode.c',RELEASE_TAG='v1.0.0',
                RELEASE_SHA='d'*40,RELEASE_REQUESTED_AT='2026-10-23T00:00:00Z',RELEASE_RUN='902',
                GITHUB_RUN_ID='1001',RELEASE_PARENT='',
                GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/orchestrate-packages.yml@refs/heads/main'):
            repository.run('bash',str(repository.ROOT/'ci/publish/status.sh'),str(self.root),'reserve')
        latest = json.loads(self.git('show','main:status.json',cwd=self.remote))['requests']['snode.c']['v1.0.0']
        self.assertEqual((latest['capture'],latest['sha'],latest['revision']),('1001','d'*40,'4'))
        self.assertNotIn('observation',latest)
        return None

    def test_lower_direct_definition_does_not_replace_highest_graph_at_cas(self):
        graph = copy.deepcopy(self.graph)
        highest = copy.deepcopy(self.state['requests']['mqttsuite']['v1.0.0']['definition'])
        graph['mqttsuite']['depends_on'] = []
        path = self.base/'lower-direct.json'
        publication.write(path,dict(projects=graph))
        with patch.dict(os.environ,CI_DEFINITIONS=str(path),RELEASE_PROJECT='mqttsuite',RELEASE_TAG='v0.9.0',
                RELEASE_SHA='d'*40,RELEASE_REQUESTED_AT='2026-10-23T00:00:00Z',RELEASE_RUN='902',
                GITHUB_RUN_ID='1001',RELEASE_PARENT='',
                GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/orchestrate-packages.yml@refs/heads/main'):
            repository.run('bash',str(repository.ROOT/'ci/publish/status.sh'),str(self.root),'reserve')
        remote = json.loads(self.git('show','main:status.json',cwd=self.remote))
        self.assertEqual(repository.requested_projects(remote['requests'])['mqttsuite'],highest)
        self.assertEqual(remote['requests']['mqttsuite']['v0.9.0']['definition']['depends_on'],[])
        return None

    def test_moved_highest_definition_cannot_collide_at_cas(self):
        graph = copy.deepcopy(self.graph)
        graph['mqttsuite']['package'] = graph['snode.c']['package']
        path = self.base/'moved-highest.json'
        publication.write(path,dict(projects=graph))
        before = self.git('show','main:status.json',cwd=self.remote)
        with patch.dict(os.environ,CI_DEFINITIONS=str(path),RELEASE_PROJECT='mqttsuite',RELEASE_TAG='v1.0.0',
                RELEASE_SHA='d'*40,RELEASE_REQUESTED_AT='2026-10-23T00:00:00Z',RELEASE_RUN='902',
                GITHUB_RUN_ID='1001',RELEASE_PARENT='',
                GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/orchestrate-packages.yml@refs/heads/main'), \
                self.assertRaises(subprocess.CalledProcessError):
            repository.run('bash',str(repository.ROOT/'ci/publish/status.sh'),str(self.root),'reserve')
        self.assertEqual(self.git('show','main:status.json',cwd=self.remote),before)
        return None

    def test_scope_loss_keeps_unregistered_reservation_across_wakes(self):
        request = dict(definition=self.graph['snode.c'],capture='999',sha='a'*40,tag='v1.0.0',
                       at='2026-10-22T00:00:00Z',run='900',revision='3',eligible=True)
        self.state['requests']['snode.c']['v1.0.0'] = copy.deepcopy(request)
        self.save()
        original = self.api
        def denied(path,payload=None,token=None):
            if path == f'repos/{dispatch.COORDINATOR}/actions/runs/999':
                raise dispatch.ApiError(403,'Capture scope unavailable')
            return original(path,payload,token)
        with patch.object(dispatch,'api',side_effect=denied):
            for _ in range(3):
                latest = publication.read(self.root/'status.json')['requests']['snode.c']['v1.0.0']
                now = latest.get('observation',{}).get('retry_at',dispatch.time.time())+1
                with patch.object(dispatch.time,'time',return_value=now):
                    self.tick()
                latest = publication.read(self.root/'status.json')['requests']['snode.c']['v1.0.0']
                self.assertEqual({k:v for k,v in latest.items() if k!='observation'},request)
                self.assertEqual(latest['observation']['category'],'configuration')
        self.assertEqual(self.posts,[])
        return None

    def test_stale_direct_artifact_overlap_off_keeps_existing_publication_path(self):
        info = self.diamond()
        self.add_capture('join','400',revision='3',cause='release')
        old = copy.deepcopy(info)
        old['releases']['snode.c']['v1.0.0']['revision'] = '1'
        required = list(repository.dependencies('join',self.graph))
        request = dict(kind='build',capture='400',project='join',target=self.row['id'],runner=self.row['runner'],
            publication=self.git('rev-parse','HEAD',cwd=self.root),intent='direct-join',actor='coordinator[bot]',
            created='2026-10-22T00:00:00Z')
        node = dict(status='publishing',cause='release',builds=2,publications=0,waiting=False,
            artifact={'id':5,'digest':'sha256:'+'a'*64},requires=required,dependencies=repository.binding(old,required),
            source=dict(run=900,attempt=1),job=1900,request=request)
        self.state['runs']['400']['nodes'] = {self.row['id']+'/join':node}
        self.runs['SNodeC/join',900] = dict(id=900,status='completed',conclusion='success',run_attempt=1)
        self.artifacts['SNodeC/join',900] = [dict(id=5,expired=False)]
        self.save()
        with patch.dict(dispatch.CONFIG['settings'],rebuild_overlap=False):
            self.tick()
        after = self.node('join','400')
        self.assertEqual((after['builds'],after['publications'],after['cause']),(2,1,'release'))
        self.assertEqual(after['artifact'],node['artifact'])
        posts = [(endpoint,json.loads(payload['inputs']['request'])) for endpoint,payload in self.posts
                 if json.loads(payload['inputs']['request'])['project']=='join']
        self.assertEqual(len(posts),1)
        self.assertIn('sign-and-publish-packages.yml',posts[0][0])
        self.assertEqual(posts[0][1]['capture'],'400')
        return None

    def test_cas_moved_highest_rejects_a_concurrently_introduced_collision(self):
        self.concurrent_requests('namespace','v1.0.0')
        return None
