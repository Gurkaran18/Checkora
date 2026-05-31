"""Local runserver with an explicit HTTP-only reminder for newcomers."""
from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    help = (
        'Starts a lightweight web server for development and reminds '
        'contributors to open the site over HTTP.'
    )

    def on_bind(self, server_port):
        super().on_bind(server_port)

        if self._raw_ipv6:
            host = f'[{self.addr}]'
        elif self.addr == '0':
            host = '127.0.0.1'
        else:
            host = self.addr

        local_url = f'http://{host}:{server_port}/'
        self.stdout.write(
            self.style.WARNING(
                f'\nOpen this URL in your browser (HTTP only, not HTTPS):\n'
                f'  {local_url}\n'
                f'If the browser upgrades to https://, disable secure-connection '
                f'settings or clear HSTS for {host} in chrome://net-internals/#hsts\n'
            )
        )
