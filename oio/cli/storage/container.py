"""Container-related commands"""
import os
import logging
import cliff
import cliff.lister
import cliff.show

from oio.cli.utils import KeyValueAction


class SetPropertyCommandMixin(object):
    """Command setting quota, storage policy or generic property"""

    def patch_parser(self, parser):
        parser.add_argument(
            '--property',
            metavar='<key=value>',
            action=KeyValueAction,
            help='Property to add/update for the container(s)'
        )
        parser.add_argument(
            '--quota',
            metavar='<bytes>',
            type=int,
            help='Set the quota on the container'
        )
        parser.add_argument(
            '--storage-policy', '--stgpol',
            metavar='<storage_policy>',
            help='Set the storage policy of the container'
        )
        parser.add_argument(
            '--max-versions', '--versioning',
            metavar='<n>',
            type=int,
            help="""Set the versioning policy of the container.
 n<0 is unlimited number of versions.
 n=0 is disabled (cannot overwrite existing object).
 n=1 is suspended (can overwrite existing object).
 n>1 is maximum n versions.
"""
        )


class CreateContainer(SetPropertyCommandMixin, cliff.lister.Lister):
    """Create an object container."""

    log = logging.getLogger(__name__ + '.CreateContainer')

    def get_parser(self, prog_name):
        parser = super(CreateContainer, self).get_parser(prog_name)
        self.patch_parser(parser)
        parser.add_argument(
            'containers',
            metavar='<container-name>',
            nargs='+',
            help='New container name(s)'
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        properties = parsed_args.property
        system = dict()
        if parsed_args.quota is not None:
            system['sys.m2.quota'] = str(parsed_args.quota)
        if parsed_args.storage_policy is not None:
            system['sys.m2.policy.storage'] = parsed_args.storage_policy
        if parsed_args.max_versions is not None:
            system['sys.m2.policy.version'] = str(parsed_args.max_versions)

        results = []
        account = self.app.client_manager.get_account()
        if len(parsed_args.containers) > 1:
            results = self.app.client_manager.storage.container_create_many(
                account,
                parsed_args.containers,
                properties=properties,
                system=system)

        else:
            for container in parsed_args.containers:
                success = self.app.client_manager.storage.container_create(
                    account,
                    container,
                    properties=properties,
                    system=system)
                results.append((container, success))

        columns = ('Name', 'Created')
        res_gen = (r for r in results)
        return columns, res_gen


class SetContainer(SetPropertyCommandMixin, cliff.command.Command):
    """Set container properties, quota, storage policy or versioning."""

    log = logging.getLogger(__name__ + '.SetContainer')

    def get_parser(self, prog_name):
        parser = super(SetContainer, self).get_parser(prog_name)
        self.patch_parser(parser)
        parser.add_argument(
            'container',
            metavar='<container>',
            help='Container to modify'
        )
        parser.add_argument(
            '--clear',
            dest='clear',
            default=False,
            help='Clear previous properties',
            action="store_true"
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        properties = parsed_args.property
        system = dict()
        if parsed_args.quota is not None:
            system['sys.m2.quota'] = str(parsed_args.quota)
        if parsed_args.storage_policy is not None:
            system['sys.m2.policy.storage'] = parsed_args.storage_policy
        if parsed_args.max_versions is not None:
            system['sys.m2.policy.version'] = str(parsed_args.max_versions)

        self.app.client_manager.storage.container_set_properties(
            self.app.client_manager.get_account(),
            parsed_args.container,
            properties,
            clear=parsed_args.clear,
            system=system
        )


class TouchContainer(cliff.command.Command):
    """Touch an object container, triggers asynchronous treatments on it."""

    log = logging.getLogger(__name__ + '.TouchContainer')

    def get_parser(self, prog_name):
        parser = super(TouchContainer, self).get_parser(prog_name)
        parser.add_argument(
            'containers',
            metavar='<container>',
            nargs='+',
            help='Container(s) to delete'
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        for container in parsed_args.containers:
            self.app.client_manager.storage.container_touch(
                self.app.client_manager.get_account(),
                container
            )


class DeleteContainer(cliff.command.Command):
    """Delete an object container."""

    log = logging.getLogger(__name__ + '.DeleteContainer')

    def get_parser(self, prog_name):
        parser = super(DeleteContainer, self).get_parser(prog_name)
        parser.add_argument(
            'containers',
            metavar='<container>',
            nargs='+',
            help='Container(s) to delete'
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        for container in parsed_args.containers:
            self.app.client_manager.storage.container_delete(
                self.app.client_manager.get_account(),
                container
            )


class ShowContainer(cliff.show.ShowOne):
    """Display information about an object container."""

    log = logging.getLogger(__name__ + '.ShowContainer')

    def get_parser(self, prog_name):
        parser = super(ShowContainer, self).get_parser(prog_name)
        parser.add_argument(
            'container',
            metavar='<container>',
            help='Name of the container to display information about'
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        account = self.app.client_manager.get_account()

        # The command is named 'show' but we must call
        # container_get_properties() because container_show() does
        # not return system properties (and we need them).
        data = self.app.client_manager.storage.container_get_properties(
            account,
            parsed_args.container
        )

        sys = data['system']
        info = {'account': sys['sys.account'],
                'base_name': sys['sys.name'],
                'container': sys['sys.user.name'],
                'ctime': sys['sys.m2.ctime'],
                'bytes_usage': sys.get('sys.m2.usage', 0),
                'quota': sys.get('sys.m2.quota', "Namespace default"),
                'objects': sys.get('sys.m2.objects', 0),
                'storage_policy': sys.get('sys.m2.policy.storage',
                                          "Namespace default"),
                'max_versions': sys.get('sys.m2.policy.version',
                                        "Namespace default"),
                }
        for k, v in data['properties'].iteritems():
            info['meta.' + k] = v
        return zip(*sorted(info.iteritems()))


class ListContainer(cliff.lister.Lister):
    """List containers."""

    log = logging.getLogger(__name__ + '.ListContainer')

    @property
    def formatter_default(self):
        return "value"

    def get_parser(self, prog_name):
        parser = super(ListContainer, self).get_parser(prog_name)
        parser.add_argument(
            '--prefix',
            metavar='<prefix>',
            help='Filter list using <prefix>'
        )
        parser.add_argument(
            '--delimiter',
            metavar='<delimiter>',
            help='Delimiter'
        )
        parser.add_argument(
            '--marker',
            metavar='<marker>',
            help='Marker for paging'
        )
        parser.add_argument(
            '--end-marker',
            metavar='<end-marker>',
            help='End marker for paging'
        )
        parser.add_argument(
            '--limit',
            metavar='<limit>',
            help='Limit the number of containers returned'
        )
        parser.add_argument(
            '--no-paging', '--full',
            dest='full_listing',
            default=False,
            help='List all containers without paging',
            action="store_true"
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        kwargs = {}
        if parsed_args.prefix:
            kwargs['prefix'] = parsed_args.prefix
        if parsed_args.marker:
            kwargs['marker'] = parsed_args.marker
        if parsed_args.end_marker:
            kwargs['end_marker'] = parsed_args.end_marker
        if parsed_args.delimiter:
            kwargs['delimiter'] = parsed_args.delimiter
        if parsed_args.limit:
            kwargs['limit'] = parsed_args.limit

        account = self.app.client_manager.get_account()

        columns = ('Name', 'Bytes', 'Count')

        if parsed_args.full_listing:
            def full_list():
                listing = self.app.client_manager.storage.container_list(
                    account, **kwargs)
                for element in listing:
                    yield element

                while listing:
                    kwargs['marker'] = listing[-1][0]
                    listing = self.app.client_manager.storage.container_list(
                        account, **kwargs)
                    if listing:
                        for element in listing:
                            yield element

            l = full_list()
        else:
            l = self.app.client_manager.storage.container_list(
                account, **kwargs)

        results = ((v[0], v[2], v[1]) for v in l)
        return columns, results


class UnsetContainer(cliff.command.Command):
    """Unset container properties."""

    log = logging.getLogger(__name__ + '.UnsetContainer')

    def get_parser(self, prog_name):
        parser = super(UnsetContainer, self).get_parser(prog_name)
        parser.add_argument(
            'container',
            metavar='<container>',
            help='Container to modify'
        )
        parser.add_argument(
            '--property',
            metavar='<key>',
            action='append',
            default=[],
            help='Property to remove from container',
        )
        parser.add_argument(
            '--storage-policy', '--stgpol',
            action='store_true',
            help='Reset the storage policy of the container '
                 'to the namespace default'
        )
        parser.add_argument(
            '--max-versions', '--versioning',
            action='store_true',
            help='Reset the versioning policy of the container '
                 'to the namespace default'
        )
        parser.add_argument(
            '--quota',
            action='store_true',
            help='Reset the quota of the container '
                 'to the namespace default'
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        properties = parsed_args.property
        system = dict()
        if parsed_args.storage_policy:
            system['sys.m2.policy.storage'] = ''
        if parsed_args.max_versions:
            system['sys.m2.policy.version'] = ''
        if parsed_args.quota:
            system['sys.m2.quota'] = ''

        if properties:
            self.app.client_manager.storage.container_del_properties(
                self.app.client_manager.get_account(),
                parsed_args.container,
                properties)
        if system:
            self.app.client_manager.storage.container_set_properties(
                self.app.client_manager.get_account(),
                parsed_args.container,
                system=system)


class SaveContainer(cliff.command.Command):
    """Save all objects of a container locally."""

    log = logging.getLogger(__name__ + '.SaveContainer')

    def get_parser(self, prog_name):
        parser = super(SaveContainer, self).get_parser(prog_name)
        parser.add_argument(
            'container',
            metavar='<container>',
            help='Container to save')
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        account = self.app.client_manager.get_account()
        container = parsed_args.container
        objs = self.app.client_manager.storage.object_list(
            account, container)

        for obj in objs['objects']:
            obj_name = obj['name']
            _, stream = self.app.client_manager.storage.object_fetch(
                account, container, obj_name)

            if not os.path.exists(os.path.dirname(obj_name)):
                if len(os.path.dirname(obj_name)) > 0:
                    os.makedirs(os.path.dirname(obj_name))
            with open(obj_name, 'wb') as f:
                for chunk in stream:
                    f.write(chunk)


class LocateContainer(cliff.show.ShowOne):
    """Locate the services in charge of a container."""

    log = logging.getLogger(__name__ + '.LocateContainer')

    def get_parser(self, prog_name):
        parser = super(LocateContainer, self).get_parser(prog_name)
        parser.add_argument(
            'container',
            metavar='<container>',
            help='Container to show'
        )

        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)

        account = self.app.client_manager.get_account()
        container = parsed_args.container

        data = self.app.client_manager.storage.container_get_properties(
            account, container)

        data_dir = self.app.client_manager.directory.list(
            account, container)

        info = {'account': data['system']['sys.account'],
                'base_name': data['system']['sys.name'],
                'name': data['system']['sys.user.name'],
                'meta0': list(),
                'meta1': list(),
                'meta2': list()}

        for d in data_dir['srv']:
            if d['type'] == 'meta2':
                info['meta2'].append(d['host'])

        for d in data_dir['dir']:
            if d['type'] == 'meta0':
                info['meta0'].append(d['host'])
            if d['type'] == 'meta1':
                info['meta1'].append(d['host'])

        for stype in ["meta0", "meta1", "meta2"]:
            info[stype] = ', '.join(info[stype])
        return zip(*sorted(info.iteritems()))
