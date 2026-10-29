from six.moves import queue, range

from .request import TLSRequest


class PoolException(Exception):
	pass


class EmptyPool(PoolException):
	pass


class ClosedPool(PoolException):
	pass


class TLSHandlerPool(object):
	"""Thread-safe connection pool for one host. Tries to emulate HTTPConnectionPool."""

	def __init__(self, tls_factory=TLSRequest, maxsize=1, **kwargs):
		self._block = kwargs.get("block", False)
		# 记住工厂与配置：非阻塞且池空时要按需新建 handler。
		self._tls_factory = tls_factory
		self._tls_config = kwargs.get("tls_config", None)
		self._pool = queue.LifoQueue(maxsize)

		for _ in range(maxsize):
			handler = tls_factory(self._tls_config)
			self._pool.put(handler, block=False)

	def send(self, options):
		"""Performs a tls request of the given TLSRequest instance, and returns
		an appropiate response.

		Args:
			options: an instance of a given tls request params.

		Returns:
			response: the response of the requests.Response.

		Raises:
			EmptyPool: if there are no more connections available to perform the request.
		"""

		tls_handler = self.get_handler_from_pool()
		try:
			response = tls_handler.send(options)
		finally:
			self.put_handler_back(tls_handler)

		return response

	def get_handler_from_pool(self):
		"""Get a tls handler. Will return a pooled handler if one is available.

		Returns:
			request.TLSRequest: tls handler, if available.

		Raises:
			EmptyPool: if the pool is empty and there are no more free handlers available.
		"""

		try:
			tls_handler = self._pool.get(block=self._block)
			return tls_handler

		except queue.Empty:
			if self._block:
				raise EmptyPool(
					"Pool reached maximum size and no more connections are allowed."
				)
			# 池是缓存不是限流器：非阻塞且空时按需新建 handler，超量部分在
			# 归还时由 put_handler_back 丢弃。旧实现直接抛 EmptyPool，共享
			# Session 在默认 maxsize=10 下第 11 个并发请求就失败。
			return self._tls_factory(self._tls_config)

		except AttributeError:
			raise ClosedPool("Pool is no longer available")

	def put_handler_back(self, tls_handler):
		"""Put a tls handler back into the pool.

		Args:
			tls_handler (request.TLSRequest): the handler to put back into the pool.
		"""
		try:
			self._pool.put(tls_handler, block=False)

		except queue.Full:
			pass  # 按需新建的 handler 超出池容量，丢弃即可（它不持有 Go 资源）

		except AttributeError:
			pass  # Pool was closed

	def close(self):
		"""Close all pooled connections and disable the pool."""
		# This is almost identical to the HTTPConnectionPool.close implementation

		if self._pool is None:
			return

		# Disable access to the pool
		old_pool, self._pool = self._pool, None

		try:
			while True:
				tls_handler = old_pool.get(block=False)
				tls_handler.close()

		except queue.Empty:
			pass  # Done.


class ProxyTLSHandlerPool(TLSHandlerPool):
	def __init__(self, proxy_url, maxsize=1, **kwargs):
		super(ProxyTLSHandlerPool, self).__init__(maxsize=maxsize, **kwargs)

		self._proxy_url = proxy_url

	@property
	def proxy_url(self):
		return self._proxy_url
