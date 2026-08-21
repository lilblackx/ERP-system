import datetime
import decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Rol(Base):
    __tablename__ = "roles"

    id_rol = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(30), nullable=False, unique=True)
    descripcion = Column(String(255))


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre_usuario = Column(String(50), nullable=False, unique=True)
    nombre = Column(String(100))
    apellido = Column(String(100))
    email = Column(String(150))
    clave = Column(String(255))
    id_rol = Column(BigInteger, ForeignKey("roles.id_rol"))
    fecha_registro = Column(DateTime, server_default=func.getdate())
    estado = Column(String(20), server_default="ACTIVO")
    id_vendedor_usuario = Column(BigInteger)

    rol = relationship("Rol")


class Vendedor(Base):
    __tablename__ = "vendedores"

    id_vendedor = Column(BigInteger, primary_key=True, autoincrement=True)
    codigo_vendedor = Column(String(20))
    identificacion_vendedor = Column(String(20))
    nombre_vendedor = Column(String(150), nullable=False)
    direccion_vendedor = Column(String(255))
    telefono_vendedor = Column(String(20))
    email_vendedor = Column(String(150))
    fecha_creacion = Column(DateTime, server_default=func.getdate())
    estado_vendedor = Column(String(20), server_default="ACTIVO")
    creado_por = Column(BigInteger, ForeignKey("usuarios.id_usuario"))


class CategoriaCliente(Base):
    __tablename__ = "categorias_cliente"

    id_categoria_cliente = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50), nullable=False, unique=True)
    descuento_porcentaje = Column(Numeric(5, 2), server_default="0.00")
    dias_credito_default = Column(Integer, server_default="0")


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente = Column(BigInteger, primary_key=True, autoincrement=True)
    id_legal = Column(String(20))
    codigo_cliente = Column(String(20), unique=True)
    identificacion_cliente = Column(String(20), unique=True)
    nombre_razon_social = Column(String(200), nullable=False)
    telefono = Column(String(20))
    email = Column(String(150))
    direccion = Column(String(255))
    limite_credito = Column(Numeric(18, 2), server_default="0.00")
    dias_credito = Column(Integer, server_default="0")
    vendedor_cliente = Column(BigInteger, ForeignKey("vendedores.id_vendedor"))
    creado_por = Column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion = Column(DateTime, server_default=func.getdate())
    id_categoria_cliente = Column(BigInteger, ForeignKey("categorias_cliente.id_categoria_cliente"))

    vendedor = relationship("Vendedor")
    categoria = relationship("CategoriaCliente")


class Permiso(Base):
    __tablename__ = "permisos"

    id_permiso: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recurso: Mapped[str] = mapped_column(String(50), nullable=False)
    accion: Mapped[str] = mapped_column(String(10), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))


class RolPermiso(Base):
    __tablename__ = "rol_permisos"

    id_rol: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id_rol"), primary_key=True)
    id_permiso: Mapped[int] = mapped_column(BigInteger, ForeignKey("permisos.id_permiso"), primary_key=True)

    rol = relationship("Rol")
    permiso = relationship("Permiso")


class ConfiguracionEmpresa(Base):
    __tablename__ = "configuracion_empresa"

    id_config: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logotipo_empresa: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    rif_empresa: Mapped[Optional[str]] = mapped_column(String(20))
    razon_social_empresa: Mapped[Optional[str]] = mapped_column(String(255))
    direccion_empresa: Mapped[Optional[str]] = mapped_column(String(255))
    telefono_empresa: Mapped[Optional[str]] = mapped_column(String(255))

    modificador = relationship("Usuario")


class Auditoria(Base):
    __tablename__ = "auditoria"

    id_auditoria: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_usuario: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    accion: Mapped[str] = mapped_column(String(50), nullable=False)
    modulo: Mapped[str] = mapped_column(String(50), nullable=False)
    detalle: Mapped[Optional[str]] = mapped_column(String)
    fecha_evento: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    usuario = relationship("Usuario")


class Categoria(Base):
    __tablename__ = "categorias"

    id_categoria: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    creador = relationship("Usuario")


class Inventario(Base):
    __tablename__ = "inventario"

    id_producto: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_categoria: Mapped[int] = mapped_column(BigInteger, ForeignKey("categorias.id_categoria"), nullable=False)
    cod_producto: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    nombre_producto: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion_producto: Mapped[Optional[str]] = mapped_column(String)
    cantidad_caja: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), server_default="0.000")
    cantidad_unidad: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), server_default="0.000")
    costo_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    fecha_registro: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    categoria = relationship("Categoria")
    creador = relationship("Usuario")


class ProductoPrecio(Base):
    __tablename__ = "producto_precios"

    id_producto_precio: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_producto: Mapped[int] = mapped_column(BigInteger, ForeignKey("inventario.id_producto"), nullable=False)
    tipo_precio: Mapped[str] = mapped_column(String(10), nullable=False)
    porcentaje_ganancia: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), server_default="0.00")
    precio_venta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    producto = relationship("Inventario")


class ControlDeTasa(Base):
    __tablename__ = "control_de_tasas"

    id_tasa: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fecha_tasa: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    tasa_dolar_bcv: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    tasa_dolar_paralelo: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(10, 2))
    tasa_cop: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(10, 2))
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    modificador = relationship("Usuario", foreign_keys=[modificado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class Proveedor(Base):
    __tablename__ = "proveedores"

    id_proveedor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_legal: Mapped[Optional[str]] = mapped_column(String(20))
    codigo_proveedor: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    identificacion_proveedor: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    nombre_razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(150))
    direccion: Mapped[Optional[str]] = mapped_column(String(255))
    limite_credito: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    dias_credito: Mapped[int] = mapped_column(Integer, server_default="0")
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    creador = relationship("Usuario")


class FacturaVenta(Base):
    __tablename__ = "factura_venta"
    __table_args__ = {"implicit_returning": False}

    id_factura: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_factura: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    id_cliente_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"), nullable=False)
    id_usuario_factura: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_emision: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    total_venta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    estado_factura: Mapped[str] = mapped_column(String(20), server_default="EMITIDA")
    id_tasa_factura: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    condicion_pago: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    observaciones_factura: Mapped[Optional[str]] = mapped_column(String(255))
    id_vendedor: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("vendedores.id_vendedor"))
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    cliente = relationship("Cliente")
    usuario = relationship("Usuario", foreign_keys=[id_usuario_factura])
    tasa = relationship("ControlDeTasa")
    vendedor = relationship("Vendedor")
    modificador = relationship("Usuario", foreign_keys=[modificado_por])


class FacturaDetalle(Base):
    __tablename__ = "factura_detalle"
    __table_args__ = {"implicit_returning": False}

    id_factura_detalle: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("factura_venta.id_factura"), nullable=False)
    id_producto_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("inventario.id_producto"), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))
    cantidad_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observaciones_item: Mapped[Optional[str]] = mapped_column(String(255))
    precio_unitario: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    factura = relationship("FacturaVenta")
    producto = relationship("Inventario")


class ComisionFactura(Base):
    __tablename__ = "comisiones_factura"

    id_comision: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monto_base_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(18, 2))
    monto_venta_comision: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(18, 2))
    estado_pago: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    fecha_calculo: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    modificador_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    id_factura_detalle: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("factura_detalle.id_factura_detalle"), nullable=False, unique=True
    )
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    modificador = relationship("Usuario", foreign_keys=[modificador_por])
    detalle = relationship("FacturaDetalle")
    creador = relationship("Usuario", foreign_keys=[creado_por])


class Compra(Base):
    __tablename__ = "compras"
    __table_args__ = {"implicit_returning": False}

    id_compra: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_compra: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    id_proveedor: Mapped[int] = mapped_column(BigInteger, ForeignKey("proveedores.id_proveedor"), nullable=False)
    id_usuario_compra: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_emision: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    total_compra: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado_compra: Mapped[Optional[str]] = mapped_column(String(20))
    id_tasa_compra: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    condicion_pago: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    observaciones_compra: Mapped[Optional[str]] = mapped_column(String(255))
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    proveedor = relationship("Proveedor")
    usuario = relationship("Usuario", foreign_keys=[id_usuario_compra])
    tasa = relationship("ControlDeTasa")
    modificador = relationship("Usuario", foreign_keys=[modificado_por])


class CompraDetalle(Base):
    __tablename__ = "compra_detalle"
    __table_args__ = {"implicit_returning": False}

    id_compra_detalle: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_compra: Mapped[int] = mapped_column(BigInteger, ForeignKey("compras.id_compra"), nullable=False)
    id_producto_compra: Mapped[int] = mapped_column(BigInteger, ForeignKey("inventario.id_producto"), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))
    cantidad_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    costo_unitario: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    observaciones_item: Mapped[Optional[str]] = mapped_column(String(255))

    compra = relationship("Compra")
    producto = relationship("Inventario")


class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"

    id_cuenta_por_cobrar: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("factura_venta.id_factura"), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    factura = relationship("FacturaVenta")
    creador = relationship("Usuario")


class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[Optional[datetime.date]] = mapped_column(Date)
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    id_compra: Mapped[int] = mapped_column(BigInteger, ForeignKey("compras.id_compra"), nullable=False)
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    compra = relationship("Compra")
    creador = relationship("Usuario")


class CuentaPorCobrarOtro(Base):
    __tablename__ = "cuentas_por_cobrar_otros"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monto_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))
    id_cliente: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_vencimiento: Mapped[Optional[datetime.date]] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), nullable=False)
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    cliente = relationship("Cliente")
    creador = relationship("Usuario")


class CuentaPorPagarOtro(Base):
    """Pese al nombre, NO son pasivos comerciales: registran dinero ya recibido en una
    cuenta bancaria de la empresa (transferencia de un cliente sin comprobante) que aun
    no se ha podido identificar/conciliar. La conciliacion aplica el monto contra la
    cuenta_por_cobrar del cliente identificado sin generar un nuevo banco_movimientos,
    ya que el ingreso del dinero ya quedo contabilizado cuando llego la transferencia."""

    __tablename__ = "cuentas_por_pagar_otros"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta_bancaria: Mapped[int] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"), nullable=False)
    id_movimiento: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("banco_movimientos.id_movimiento"))
    monto_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_recepcion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    referencia_bancaria: Mapped[Optional[str]] = mapped_column(String(100))
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    id_cliente_identificado: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"))
    conciliado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_conciliacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    cuenta_bancaria = relationship("CuentaBancaria")
    movimiento = relationship("BancoMovimiento")
    cliente_identificado = relationship("Cliente", foreign_keys=[id_cliente_identificado])
    conciliador = relationship("Usuario", foreign_keys=[conciliado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class Banco(Base):
    __tablename__ = "bancos"

    id_banco: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo_banco: Mapped[Optional[str]] = mapped_column(String(4))
    nombre_banco: Mapped[Optional[str]] = mapped_column(String(100))
    tipo_banco: Mapped[Optional[str]] = mapped_column(String(30))
    identificacion_banco: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    correo_banco: Mapped[Optional[str]] = mapped_column(String(150))
    numero_telefono_banco: Mapped[Optional[str]] = mapped_column(String(20))
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    modificador = relationship("Usuario", foreign_keys=[modificado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class CuentaBancaria(Base):
    __tablename__ = "cuentas_bancarias"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_banco: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("bancos.id_banco"))
    numero_cuenta: Mapped[Optional[str]] = mapped_column(String(30))
    tipo_cuenta_banco: Mapped[Optional[str]] = mapped_column(String(10))
    nombre_titular: Mapped[Optional[str]] = mapped_column(String(150))
    identificacion_titular: Mapped[Optional[str]] = mapped_column(String(20))
    saldo_total_banco: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    banco = relationship("Banco")
    creador = relationship("Usuario")


class Caja(Base):
    __tablename__ = "cajas"
    __table_args__ = {"implicit_returning": False}

    id_caja: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre_caja: Mapped[Optional[str]] = mapped_column(String(50))
    estado_caja: Mapped[Optional[str]] = mapped_column(String(20))
    saldo_apertura: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    saldo_cierre: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(18, 2))
    fecha_apertura: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    fecha_cierre: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    id_usuario: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    modificado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    usuario = relationship("Usuario", foreign_keys=[id_usuario])
    modificador = relationship("Usuario", foreign_keys=[modificado_por])


class PagoCobro(Base):
    __tablename__ = "pagos_cobros"
    __table_args__ = {"implicit_returning": False}

    id_pago_cobro: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta_por_cobrar: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cuentas_por_cobrar.id_cuenta_por_cobrar"), nullable=False
    )
    id_cuenta_bancaria: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    id_caja: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    id_tasa: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referencia: Mapped[Optional[str]] = mapped_column(String(100))
    fecha_pago: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    cuenta_por_cobrar = relationship("CuentaPorCobrar")
    cuenta_bancaria = relationship("CuentaBancaria")
    caja = relationship("Caja")
    tasa = relationship("ControlDeTasa")
    creador = relationship("Usuario")


class PagoProveedor(Base):
    __tablename__ = "pagos_proveedores"
    __table_args__ = {"implicit_returning": False}

    id_pago_proveedor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta_por_pagar: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cuentas_por_pagar.id_cuenta"), nullable=False
    )
    id_cuenta_bancaria: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    id_caja: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    id_tasa: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referencia: Mapped[Optional[str]] = mapped_column(String(100))
    fecha_pago: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    cuenta_por_pagar = relationship("CuentaPorPagar")
    cuenta_bancaria = relationship("CuentaBancaria")
    caja = relationship("Caja")
    tasa = relationship("ControlDeTasa")
    creador = relationship("Usuario")


class BancoMovimiento(Base):
    __tablename__ = "banco_movimientos"
    __table_args__ = {"implicit_returning": False}

    id_movimiento: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    tipo_movimiento: Mapped[Optional[str]] = mapped_column(String(15))
    monto_movimiento: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(18, 2))
    fecha_movimiento: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    referencia_movimiento: Mapped[Optional[str]] = mapped_column(String(100))
    descripcion_movimiento: Mapped[Optional[str]] = mapped_column(String(255))
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    id_pago_cobro: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("pagos_cobros.id_pago_cobro"))
    id_pago_proveedor: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pagos_proveedores.id_pago_proveedor")
    )

    cuenta = relationship("CuentaBancaria")
    creador = relationship("Usuario")
    pago_cobro = relationship("PagoCobro")
    pago_proveedor = relationship("PagoProveedor")


class CajaMovimiento(Base):
    __tablename__ = "caja_movimientos"

    id_movimiento: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_caja: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    tipo_movimiento: Mapped[Optional[str]] = mapped_column(String(10))
    descripcion_movimiento: Mapped[Optional[str]] = mapped_column(String(255))
    monto_movimiento: Mapped[Optional[decimal.Decimal]] = mapped_column(Numeric(18, 2))
    fecha_registro: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    id_pago_cobro: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("pagos_cobros.id_pago_cobro"))
    id_pago_proveedor: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("pagos_proveedores.id_pago_proveedor")
    )
    creado_por: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    caja = relationship("Caja")
    pago_cobro = relationship("PagoCobro")
    pago_proveedor = relationship("PagoProveedor")
    creador = relationship("Usuario")
