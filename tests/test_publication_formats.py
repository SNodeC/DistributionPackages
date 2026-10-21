"""The shared publication boundary retains unrelated products in every feed format."""
import copy
from pathlib import Path
import tempfile
import unittest
from support import PinnedJsonCase
from unittest.mock import patch
from ci import repository
from ci.publish import publication, openwrt, linux


class SiblingFormatsTest(PinnedJsonCase):
    def test_sibling_rebase_preserves_newer_packages_for_apt_rpm_opkg_and_apk(self):
        ids=['debian-trixie-amd64','rocky-9-x86_64','openwrt-24.10-x86_64','openwrt-25.12-x86_64']
        for target in ids:
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temporary:
                row=next(r for r in publication.targets() if r['id']==target)
                root,bundle,incoming=(Path(temporary)/n for n in ['feed','bundle','incoming'])
                folder=Path('openwrt')/row['suite']/row['arch'] if row['family']=='openwrt' else Path('linux')/row['distribution']/row['suite']/row['arch']
                directory=incoming/folder;directory.mkdir(parents=True)
                graph=copy.deepcopy(repository.PROJECTS)
                graph['demo']=copy.deepcopy(graph['snode.c']);graph['demo'].update(title='Demo',package='snodec-extra')
                graph.pop('snode.c-idp')
                extension='ipk' if row['suite']=='24.10' else 'apk' if row['family']=='openwrt' else 'deb' if row['distribution']=='debian' else 'rpm'
                def name(project,revision):
                    value=f'{graph[project]["package"]}_{revision}.{extension}'
                    return 'Packages/'+value if extension=='rpm' else value
                sources={p:{'refs/tags/v1.0.0':c*40} for p,c in [('snode.c','a'),('mqttsuite','b'),('demo','c')]}
                baseline=dict(sources=copy.deepcopy(sources),versions={p:repository.package_version(row,'1.0.0','1') for p in graph},files={},packages=['snodec','mqttsuite','snodec-extra'])
                current=copy.deepcopy(baseline)
                current['sources']['demo']={'refs/tags/v1.0.0':'d'*40}
                current['versions']['demo']=repository.package_version(row,'1.0.0','2')
                for project,revision in [('snode.c',1),('mqttsuite',1),('demo',2)]:
                    filename=name(project,revision)
                    path=root/(Path('debian/pool/trixie')/filename if extension=='deb' else Path(publication.feed_paths(row)[0])/filename)
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(filename)
                    current['files'][filename]=repository.digest(path)
                manifest=root/publication.feed_paths(row)[0]/'build.json'
                publication.write(manifest,{'targets':{row['arch']:current}} if extension=='deb' else current)
                context=dict(build_project='mqttsuite',release_project='mqttsuite',source_tags=dict.fromkeys(graph,'v1.0.0'),versions=dict.fromkeys(graph,'1.0.0'))
                profile=dict(projects=graph,baseline=baseline,context=context,sources=sources,archives={'mqttsuite':'source.tar.gz'})
                publication.write(bundle/'profiles.json',{row['id']:profile});(bundle/'archives').mkdir();(bundle/'archives/source.tar.gz').touch()
                with patch.object(repository,'activate'):
                    selected=repository.select(bundle,row['id'],'mqttsuite')
                metadata=dict(revision='2',series=row['suite'],sources=selected['sources'],context=selected['context'],versions=baseline['versions']|{'mqttsuite':repository.package_version(row,'1.0.0','2')},files={},packages=['snodec','mqttsuite','snodec-extra'])
                for project,revision in [('snode.c',1),('mqttsuite',2),('demo',1)]:
                    filename=name(project,revision);path=directory/filename
                    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(filename)
                    metadata['files'][filename]=repository.digest(path)
                if extension=='ipk':
                    (directory/'Packages').write_text('Package: mqttsuite\nVersion: 1-r2\n\nPackage: snodec-extra\nVersion: 1-r1\n\n')
                    (manifest.parent/'Packages').write_text('Package: snodec\nVersion: 1-r1\n\nPackage: snodec-extra\nVersion: 1-r2\n\n')
                publication.write(directory/'build.json',metadata)
                def sign(*args):
                    result=publication.read(directory/'build.json')
                    self.assertIn(name('demo',2),result['files'])
                    self.assertNotIn(name('demo',1),result['files'])
                    self.assertEqual(result['sources']['demo'],current['sources']['demo'])
                    self.assertEqual(result['versions']['demo'],current['versions']['demo'])
                    publication.write(manifest,{'targets':{row['arch']:result}} if extension=='deb' else result)
                    return None
                def index(*args):
                    self.assertIn(str(directory/name('demo',2)),args)
                    self.assertNotIn(str(directory/name('demo',1)),args)
                    (directory/'packages.adb').write_text('index rebuilt from retained bytes')
                    return None
                with patch.object(repository,'PROJECTS',graph),patch.object(publication,'PROJECTS',graph),patch.object(repository,'REPOSITORIES',tuple(graph)+('unpublished',)),patch.object(publication,'REPOSITORIES',tuple(graph)+('unpublished',)),patch.object(repository,'activate'),patch.object(publication,'activate'),patch.object(repository,'publish',side_effect=sign),patch.object(linux,'publish',side_effect=sign),patch.object(openwrt,'run',side_effect=index),patch('ci.publish.cleanup.cleanup'):
                    publication.publish(root,bundle,incoming,row,dict(revisions={'mqttsuite':'2'},profiles_hash=repository.digest(bundle/'profiles.json')),'mqttsuite')
        return None

    def test_unknown_retained_sibling_ownership_fails_before_feed_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,bundle,incoming=(Path(temporary)/n for n in ('feed','bundle','incoming'))
            row=next(r for r in publication.targets() if r['id']=='debian-trixie-amd64')
            directory=incoming/'linux/debian/trixie/amd64'
            directory.mkdir(parents=True)
            package=directory/'snodec_2.deb'
            package.write_bytes(b'unsigned fixture')
            publication.write(directory/'build.json',dict(files={package.name:repository.digest(package)}))
            publication.write(bundle/'profiles.json',{row['id']:{'projects':repository.PROJECTS}})
            publication.write(root/'debian/dists/trixie/build.json',dict(targets={'amd64':dict(sources={'historical':{'refs/tags/v1.0.0':'a'*40}},files={'historical_1.deb':'f'*64})}))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(publication,'activate'),self.assertRaisesRegex(RuntimeError,'Retained sibling ownership unavailable'):
                publication.publish(root,bundle,incoming,row,dict(profiles_hash=repository.digest(bundle/'profiles.json'),revisions={'snode.c':'2'}),'snode.c')
            self.assertEqual({str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()},before)
        return None

    def test_new_sdk_product_preserves_every_retained_version(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            sdk,bundle,output=(Path(temporary)/n for n in ['sdk','bundle','output'])
            feed=sdk/'bin/packages/test/snodec';feed.mkdir(parents=True)
            publication.write(sdk/'ci-sdk.json',dict(arch='test',series='24.10'))
            for name in ['demo.ipk','Packages','Packages.gz']:
                (feed/name).write_bytes(b'fixture')
            publication.write(bundle/'context.json',dict(build_project='demo',versions={'demo':'1.0.0','snode.c':'2.0.0','mqttsuite':'1.0.2'}))
            publication.write(bundle/'sources.json',{})
            retained={'snode.c':'2.0.0-r2','mqttsuite':'1.0.2-r3'}
            publication.write(bundle/'baseline.json',dict(versions=retained))
            with patch.dict(os.environ,PACKAGE_RELEASE='9'):
                repository.stage(sdk,bundle,output)
            self.assertEqual(publication.read(output/'openwrt/24.10/test/build.json')['versions'],retained|{'demo':'1.0.0-r9'})
        return None

    def test_real_apt_indexes_are_signed_verified_and_available_by_hash(self):
        import os
        import subprocess
        from ci.publish import apt
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);home=root/'gnupg';home.mkdir(mode=0o700)
            (root/'keys').mkdir()
            package=root/'package';(package/'DEBIAN').mkdir(parents=True)
            (package/'DEBIAN/control').write_text('Package: demo\nVersion: 1.0.0-1\nArchitecture: amd64\nMaintainer: Fixture <fixture@example.invalid>\nDescription: local signing fixture\n')
            feed=root/'apt';pool=feed/'pool/trixie';pool.mkdir(parents=True)
            repository.run('dpkg-deb','--build','--root-owner-group',str(package),str(pool/'demo.deb'))
            repository.run('gpg','--homedir',str(home),'--batch','--pinentry-mode','loopback','--passphrase','','--quick-generate-key','Fixture <fixture@example.invalid>','rsa2048','sign','1d',stderr=subprocess.DEVNULL)
            private=repository.run('gpg','--homedir',str(home),'--batch','--armor','--export-secret-keys')
            (root/'keys/snodec-apt.asc').write_text(repository.run('gpg','--homedir',str(home),'--batch','--armor','--export'))
            with patch.object(apt,'ROOT',root),patch.dict(os.environ,APT_SIGNING_KEY=private):
                apt.index(feed,'trixie',{'amd64':{}})
            dist=feed/'dists/trixie'
            self.assertIn('BEGIN PGP SIGNED MESSAGE',(dist/'InRelease').read_text())
            self.assertIn('BEGIN PGP SIGNATURE',(dist/'Release.gpg').read_text())
            index=dist/'main/binary-amd64/Packages'
            self.assertIn('Package: demo',index.read_text())
            self.assertEqual((index.parent/'by-hash/SHA256'/repository.digest(index)).read_bytes(),index.read_bytes())
        return None

    def test_apt_uses_the_built_repository_image_and_architectures(self):
        import os
        import subprocess
        from ci.publish import apt
        graph=copy.deepcopy(repository.PROJECTS)
        graph['mqttsuite']['matrix']['linux']=[dict(distribution='debian',suite='trixie',image='debian:trixie-slim',architectures=['amd64']),dict(distribution='debian',suite='trixie',image='arm64v8/debian:trixie',architectures=['arm64'])]
        graph['mqttsuite']['matrix']['raspberrypi']['bookworm']['sha256']='d'*64
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bundle=root/'bundle';packages=root/'packages';packages.mkdir()
            package=root/'package';(package/'DEBIAN').mkdir(parents=True)
            (package/'DEBIAN/control').write_text('Package: mqttsuite\nVersion: 1.0.0-1~trixie\nArchitecture: amd64\nMaintainer: Fixture <fixture@example.invalid>\nDescription: repository-owned image fixture\n')
            repository.run('dpkg-deb','--build','--root-owner-group',str(package),str(packages/'mqttsuite.deb'))
            (packages/'mqttsuite.packages').write_text('mqttsuite\n')
            for name,value in dict(context={'build_project':'mqttsuite'},sources={'mqttsuite':{'refs/tags/v1.0.0':'a'*40}},checksums={}).items():
                publication.write(bundle/(name+'.json'),value)
            home=root/'gnupg';home.mkdir(mode=0o700);(root/'keys').mkdir()
            repository.run('gpg','--homedir',str(home),'--batch','--pinentry-mode','loopback','--passphrase','','--quick-generate-key','Image fixture <fixture@example.invalid>','rsa2048','sign','1d',stderr=subprocess.DEVNULL)
            private=repository.run('gpg','--homedir',str(home),'--batch','--armor','--export-secret-keys')
            (root/'keys/snodec-apt.asc').write_text(repository.run('gpg','--homedir',str(home),'--batch','--armor','--export'))
            output,feed=root/'output',root/'feed'
            with patch.dict(apt.PROJECTS,graph,clear=True),patch.object(apt,'ROOT',root),patch.dict(os.environ,PACKAGE_RELEASE='1',APT_SIGNING_KEY=private):
                apt.stage('trixie',packages,bundle,output,'debian')
                info=publication.read(output/'debian/trixie/amd64/build.json')
                self.assertEqual(info['image'],'debian:trixie-slim')
                self.assertEqual(set(apt.images('debian','mqttsuite')),{('trixie','amd64'),('trixie','arm64')})
                self.assertEqual(apt.images('debian','mqttsuite')['trixie','arm64'],'arm64v8/debian:trixie')
                self.assertNotEqual(apt.images('debian','snode.c')['trixie','amd64'],info['image'])
                self.assertEqual(apt.images('raspberrypios','mqttsuite')['bookworm','arm64']['sha256'],'d'*64)
                apt.publish(output,feed,bundle,'debian')
                signed=publication.read(feed/'debian/dists/trixie/build.json')['targets']['amd64']
                self.assertEqual(signed['image'],'debian:trixie-slim')
                self.assertTrue((feed/'debian/dists/trixie/InRelease').exists())
        return None
