import datetime
import decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
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

    id_rol: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(255))


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre_usuario: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    nombre: Mapped[str | None] = mapped_column(String(100))
    apellido: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(150))
    clave: Mapped[str | None] = mapped_column(String(255))
    id_rol: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("roles.id_rol"))
    fecha_registro: Mapped[datetime.datetime | None] = mapped_column(DateTime, server_default=func.getdate())
    estado: Mapped[str | None] = mapped_column(String(20), server_default="ACTIVO")
    id_vendedor_usuario: Mapped[int | None] = mapped_column(BigInteger)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # NULL = no bloqueado; solo un codigo (o un ADMIN) lo limpia, no expira solo.
    bloqueado_desde: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    rol = relationship("Rol")


class Vendedor(Base):
    __tablename__ = "vendedores"

    id_vendedor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo_vendedor: Mapped[str | None] = mapped_column(String(20))
    identificacion_vendedor: Mapped[str | None] = mapped_column(String(20))
    nombre_vendedor: Mapped[str] = mapped_column(String(150), nullable=False)
    direccion_vendedor: Mapped[str | None] = mapped_column(String(255))
    telefono_vendedor: Mapped[str | None] = mapped_column(String(20))
    email_vendedor: Mapped[str | None] = mapped_column(String(150))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime, server_default=func.getdate())
    estado_vendedor: Mapped[str | None] = mapped_column(String(20), server_default="ACTIVO")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))


class CategoriaCliente(Base):
    __tablename__ = "categorias_cliente"

    id_categoria_cliente: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    dias_credito_default: Mapped[int | None] = mapped_column(Integer, server_default="0")


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_legal: Mapped[str | None] = mapped_column(String(20))
    codigo_cliente: Mapped[str | None] = mapped_column(String(20), unique=True)
    identificacion_cliente: Mapped[str | None] = mapped_column(String(20), unique=True)
    nombre_razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    direccion: Mapped[str | None] = mapped_column(String(255))
    limite_credito: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2), server_default="0.00")
    dias_credito: Mapped[int | None] = mapped_column(Integer, server_default="0")
    vendedor_cliente: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vendedores.id_vendedor"))
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime, server_default=func.getdate())
    id_categoria_cliente: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categorias_cliente.id_categoria_cliente")
    )
    estado_cliente: Mapped[str | None] = mapped_column(String(20), server_default="ACTIVO")

    vendedor = relationship("Vendedor")
    categoria = relationship("CategoriaCliente")


class Permiso(Base):
    __tablename__ = "permisos"

    id_permiso: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recurso: Mapped[str] = mapped_column(String(50), nullable=False)
    accion: Mapped[str] = mapped_column(String(10), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255))


class RolPermiso(Base):
    __tablename__ = "rol_permisos"

    id_rol: Mapped[int] = mapped_column(BigInteger, ForeignKey("roles.id_rol"), primary_key=True)
    id_permiso: Mapped[int] = mapped_column(BigInteger, ForeignKey("permisos.id_permiso"), primary_key=True)

    rol = relationship("Rol")
    permiso = relationship("Permiso")


class ConfiguracionEmpresa(Base):
    __tablename__ = "configuracion_empresa"

    id_config: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logotipo_empresa: Mapped[bytes | None] = mapped_column(LargeBinary)
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    rif_empresa: Mapped[str | None] = mapped_column(String(20))
    razon_social_empresa: Mapped[str | None] = mapped_column(String(255))
    direccion_empresa: Mapped[str | None] = mapped_column(String(255))
    telefono_empresa: Mapped[str | None] = mapped_column(String(255))
    pie_pagina_empresa: Mapped[str | None] = mapped_column(String(500))
    # IVA activable por empresa (algunas operan bajo regimenes/rubros exentos) y con
    # porcentaje ajustable -- VentaService snapshotea ambos en cada factura al emitirla
    # (FacturaVenta.iva_aplicado/porcentaje_iva_aplicado) para que un cambio posterior de
    # este porcentaje no altere retroactivamente el IVA ya facturado.
    iva_activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    iva_porcentaje: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="16.00")
    # Nombre de impresora tal como lo reporta QPrinterInfo -- ver
    # app/ui/factura_pdf.py::imprimir_factura y migrations/0023.
    impresora_predeterminada: Mapped[str | None] = mapped_column(String(255))

    modificador = relationship("Usuario")


class Auditoria(Base):
    __tablename__ = "auditoria"

    id_auditoria: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_usuario: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    accion: Mapped[str] = mapped_column(String(50), nullable=False)
    modulo: Mapped[str] = mapped_column(String(50), nullable=False)
    detalle: Mapped[str | None] = mapped_column(String)
    fecha_evento: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    usuario = relationship("Usuario")


class CodigoVerificacion(Base):
    __tablename__ = "codigos_verificacion"

    id_codigo: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_usuario: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    codigo_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    fecha_expiracion: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    usado: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    intentos_verificacion: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    usuario = relationship("Usuario")


class Categoria(Base):
    __tablename__ = "categorias"

    id_categoria: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    creador = relationship("Usuario")


class Inventario(Base):
    __tablename__ = "inventario"

    id_producto: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_categoria: Mapped[int] = mapped_column(BigInteger, ForeignKey("categorias.id_categoria"), nullable=False)
    cod_producto: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    nombre_producto: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion_producto: Mapped[str | None] = mapped_column(String)
    cantidad_caja: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), server_default="0.000")
    cantidad_unidad: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), server_default="0.000")
    costo_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    fecha_registro: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    estado_producto: Mapped[str] = mapped_column(String(20), server_default="ACTIVO")

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
    tasa_dolar_paralelo: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    tasa_cop: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    modificador = relationship("Usuario", foreign_keys=[modificado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class Proveedor(Base):
    __tablename__ = "proveedores"

    id_proveedor: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_legal: Mapped[str | None] = mapped_column(String(20))
    codigo_proveedor: Mapped[str | None] = mapped_column(String(20), unique=True)
    identificacion_proveedor: Mapped[str | None] = mapped_column(String(20), unique=True)
    nombre_razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    direccion: Mapped[str | None] = mapped_column(String(255))
    limite_credito: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    dias_credito: Mapped[int] = mapped_column(Integer, server_default="0")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    estado_proveedor: Mapped[str] = mapped_column(String(20), server_default="ACTIVO")

    creador = relationship("Usuario")


class FacturaVenta(Base):
    __tablename__ = "factura_venta"
    __table_args__ = {"implicit_returning": False}

    id_factura: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_factura: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # Numero de control fiscal (factura digital, sin impresora fiscal certificada):
    # distinto de numero_factura (referencia de negocio) -- ver
    # migrations/0019_factura_numero_control_iva.sql. Mismo patron placeholder+flush+
    # update que numero_factura, ver _numero_control_temporal() en ventas.py.
    numero_control: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    id_cliente_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"), nullable=False)
    id_usuario_factura: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_emision: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    total_venta: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    # IVA snapshoteado al emitir (no recalculado si config_empresa cambia despues -- ver
    # ConfiguracionEmpresa.iva_activo/iva_porcentaje). total_venta sigue siendo el
    # subtotal puro de las lineas (lo que recalculan los triggers existentes,
    # trg_factura_total_*); monto_iva es lo que se le suma para el total a cobrar.
    iva_aplicado: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    porcentaje_iva_aplicado: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="0.00"
    )
    monto_iva: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    estado_factura: Mapped[str] = mapped_column(String(20), server_default="EMITIDA")
    id_tasa_factura: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    condicion_pago: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    observaciones_factura: Mapped[str | None] = mapped_column(String(255))
    id_vendedor: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendedores.id_vendedor"), nullable=False)
    # Descuento manual de factura completa (no por linea -- el descuento por item se
    # maneja directamente bajando precio_unitario, ver ComisionService/VentaService).
    # Igual que precio_unitario < precio de lista, requiere autorizacion de un usuario
    # con permiso 'descuentos'/'crear' -- ver migrations/0020_descuentos_autorizacion.sql,
    # migrations/0021_permiso_autorizar_descuento.sql y VentaService.emitir_factura().
    monto_descuento: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    motivo_descuento: Mapped[str | None] = mapped_column(String(255))
    autorizado_por_descuento: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    # Dias de credito efectivamente aplicados a esta factura (configurados en el cliente, o
    # personalizados con autorizacion) -- ver migrations/0025_autorizacion_dias_credito.sql
    # y VentaService.emitir_factura(). NULL en facturas de contado. motivo_dias_credito/
    # autorizado_por_dias_credito solo se pueblan cuando el valor difiere del configurado en
    # Cliente.dias_credito (requiere permiso 'creditos'/'crear').
    dias_credito_aplicados: Mapped[int | None] = mapped_column(Integer)
    motivo_dias_credito: Mapped[str | None] = mapped_column(String(255))
    autorizado_por_dias_credito: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    # Vuelto (cambio) de una factura de contado cuando las formas de pago exceden
    # total_a_cobrar -- el excedente siempre se entrega al cliente (no hay "saldo a
    # favor" como metodo de vuelto). monto_vuelto=0.00 en toda factura sin vuelto
    # (incluidas todas las de credito). Efectivo es libre (metodo_vuelto/
    # referencia_vuelto/autorizado_por_vuelto quedan NULL); pago_movil/transferencia
    # exigen referencia_vuelto + autorizado_por_vuelto (permiso 'vueltos_bancarios'/
    # 'crear', mismo mecanismo que 'descuentos'/'creditos') -- ver
    # migrations/0027_vuelto_factura.sql y VentaService.emitir_factura().
    monto_vuelto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    metodo_vuelto: Mapped[str | None] = mapped_column(String(20))
    referencia_vuelto: Mapped[str | None] = mapped_column(String(50))
    autorizado_por_vuelto: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_autorizacion_vuelto: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    cliente = relationship("Cliente")
    usuario = relationship("Usuario", foreign_keys=[id_usuario_factura])
    tasa = relationship("ControlDeTasa")
    vendedor = relationship("Vendedor")
    modificador = relationship("Usuario", foreign_keys=[modificado_por])
    autorizador_descuento = relationship("Usuario", foreign_keys=[autorizado_por_descuento])
    autorizador_dias_credito = relationship("Usuario", foreign_keys=[autorizado_por_dias_credito])
    autorizador_vuelto = relationship("Usuario", foreign_keys=[autorizado_por_vuelto])


class FacturaDetalle(Base):
    __tablename__ = "factura_detalle"
    __table_args__ = {"implicit_returning": False}

    id_factura_detalle: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("factura_venta.id_factura"), nullable=False)
    id_producto_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("inventario.id_producto"), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    cantidad_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    observaciones_item: Mapped[str | None] = mapped_column(String(255))
    precio_unitario: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    factura = relationship("FacturaVenta")
    producto = relationship("Inventario")


class ComisionFactura(Base):
    __tablename__ = "comisiones_factura"

    id_comision: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monto_base_comision: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    monto_venta_comision: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    estado_pago: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    fecha_calculo: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    modificador_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    id_factura_detalle: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("factura_detalle.id_factura_detalle"), nullable=False, unique=True
    )
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    # id_vendedor denormalizado desde factura_venta.id_vendedor al calcular (C14): evita un
    # join de 2 saltos (comisiones_factura -> factura_detalle -> factura_venta) en cada
    # consulta de "comisiones pendientes de vendedor X".
    id_vendedor: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vendedores.id_vendedor"))
    # Monto ya calculado y piso-en-cero (max(0, monto_venta_comision - monto_base_comision))
    # -- lo que realmente se le debe al vendedor por esta linea.
    monto_comision: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    id_pago_comision: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_comisiones.id_pago_comision"))

    modificador = relationship("Usuario", foreign_keys=[modificador_por])
    detalle = relationship("FacturaDetalle")
    creador = relationship("Usuario", foreign_keys=[creado_por])
    vendedor = relationship("Vendedor")
    pago_comision = relationship("PagoComision")


class Compra(Base):
    __tablename__ = "compras"
    __table_args__ = {"implicit_returning": False}

    id_compra: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_compra: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    id_proveedor: Mapped[int] = mapped_column(BigInteger, ForeignKey("proveedores.id_proveedor"), nullable=False)
    id_usuario_compra: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_emision: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    total_compra: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado_compra: Mapped[str | None] = mapped_column(String(20))
    id_tasa_compra: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    condicion_pago: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    observaciones_compra: Mapped[str | None] = mapped_column(String(255))
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

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
    descripcion: Mapped[str | None] = mapped_column(String(255))
    cantidad_producto: Mapped[decimal.Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    costo_unitario: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    observaciones_item: Mapped[str | None] = mapped_column(String(255))

    compra = relationship("Compra")
    producto = relationship("Inventario")


class CuentaPorCobrar(Base):
    __tablename__ = "cuentas_por_cobrar"

    id_cuenta_por_cobrar: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_factura: Mapped[int] = mapped_column(BigInteger, ForeignKey("factura_venta.id_factura"), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    factura = relationship("FacturaVenta")
    creador = relationship("Usuario")


class CuentaPorPagar(Base):
    __tablename__ = "cuentas_por_pagar"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[datetime.date | None] = mapped_column(Date)
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    id_compra: Mapped[int] = mapped_column(BigInteger, ForeignKey("compras.id_compra"), nullable=False)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)

    compra = relationship("Compra")
    creador = relationship("Usuario")


class CuentaPorCobrarOtro(Base):
    __tablename__ = "cuentas_por_cobrar_otros"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    monto_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    id_cliente: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_vencimiento: Mapped[datetime.date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(10), nullable=False)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

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
    id_cuenta_bancaria: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"), nullable=False
    )
    id_movimiento: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("banco_movimientos.id_movimiento"))
    monto_total: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    saldo_pendiente: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_recepcion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    referencia_bancaria: Mapped[str | None] = mapped_column(String(100))
    descripcion: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(10), server_default="pendiente")
    id_cliente_identificado: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"))
    conciliado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_conciliacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    cuenta_bancaria = relationship("CuentaBancaria")
    movimiento = relationship("BancoMovimiento")
    cliente_identificado = relationship("Cliente", foreign_keys=[id_cliente_identificado])
    conciliador = relationship("Usuario", foreign_keys=[conciliado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class NotaCreditoCliente(Base):
    """Saldo a favor del cliente generado al anular una factura que ya tenia pagos
    aplicados: en vez de revertir el pago (borrar/editar caja_movimientos o
    banco_movimientos ya registrados, potencialmente de un turno ya cerrado o
    conciliado), el dinero ya cobrado queda como credito disponible para aplicar a una
    compra futura o devolver luego como una operacion nueva, real y fechada -- ver
    NotaCreditoService y la nota en VentaService.anular_factura.

    Es un documento fiscal que la empresa emite (reduce lo que el cliente le debe), por
    eso numero_nota_credito es correlativo y unico, igual que factura_venta.numero_factura
    -- reportable al SENIAT cuando se solicite."""

    __tablename__ = "notas_credito_clientes"

    id_nota_credito: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    numero_nota_credito: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    id_cliente: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id_cliente"), nullable=False)
    id_factura_origen: Mapped[int] = mapped_column(BigInteger, ForeignKey("factura_venta.id_factura"), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    saldo_disponible: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(15), server_default="disponible")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    cliente = relationship("Cliente")
    factura_origen = relationship("FacturaVenta")
    creador = relationship("Usuario")


class NotaCreditoProveedor(Base):
    """Simetrico a NotaCreditoCliente, para el lado de compras: saldo a favor de la
    empresa cuando se anula una compra que ya tenia pagos aplicados al proveedor."""

    __tablename__ = "notas_credito_proveedores"

    id_nota_credito: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_proveedor: Mapped[int] = mapped_column(BigInteger, ForeignKey("proveedores.id_proveedor"), nullable=False)
    id_compra_origen: Mapped[int] = mapped_column(BigInteger, ForeignKey("compras.id_compra"), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    saldo_disponible: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(15), server_default="disponible")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())

    proveedor = relationship("Proveedor")
    compra_origen = relationship("Compra")
    creador = relationship("Usuario")


class Banco(Base):
    __tablename__ = "bancos"

    id_banco: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    codigo_banco: Mapped[str | None] = mapped_column(String(4))
    nombre_banco: Mapped[str | None] = mapped_column(String(100))
    tipo_banco: Mapped[str | None] = mapped_column(String(30))
    identificacion_banco: Mapped[str | None] = mapped_column(String(20), unique=True)
    correo_banco: Mapped[str | None] = mapped_column(String(150))
    numero_telefono_banco: Mapped[str | None] = mapped_column(String(20))
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    estado_banco: Mapped[str] = mapped_column(String(20), server_default="ACTIVO")

    modificador = relationship("Usuario", foreign_keys=[modificado_por])
    creador = relationship("Usuario", foreign_keys=[creado_por])


class CuentaBancaria(Base):
    __tablename__ = "cuentas_bancarias"

    id_cuenta: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_banco: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bancos.id_banco"))
    numero_cuenta: Mapped[str | None] = mapped_column(String(30))
    tipo_cuenta_banco: Mapped[str | None] = mapped_column(String(10))
    nombre_titular: Mapped[str | None] = mapped_column(String(150))
    identificacion_titular: Mapped[str | None] = mapped_column(String(20))
    saldo_total_banco: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    estado_cuenta: Mapped[str] = mapped_column(String(20), server_default="ACTIVO")

    banco = relationship("Banco")
    creador = relationship("Usuario")


class Caja(Base):
    __tablename__ = "cajas"
    __table_args__ = {"implicit_returning": False}

    id_caja: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre_caja: Mapped[str | None] = mapped_column(String(50))
    estado_caja: Mapped[str | None] = mapped_column(String(20))
    saldo_apertura: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), server_default="0.00")
    saldo_cierre: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    fecha_apertura: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    fecha_cierre: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    id_usuario: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    modificado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    usuario = relationship("Usuario", foreign_keys=[id_usuario])
    modificador = relationship("Usuario", foreign_keys=[modificado_por])


class PagoCobro(Base):
    __tablename__ = "pagos_cobros"
    __table_args__ = {"implicit_returning": False}

    id_pago_cobro: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta_por_cobrar: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cuentas_por_cobrar.id_cuenta_por_cobrar"), nullable=False
    )
    id_cuenta_bancaria: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    id_caja: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    id_tasa: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    # Moneda del monto tal como se recibio (ver monto_moneda_origen); "monto" (abajo) queda
    # siempre en USD -- el equivalente que efectivamente se aplica contra saldo_pendiente,
    # ver migrations/0024_pagos_contado_multimetodo.sql.
    moneda: Mapped[str] = mapped_column(String(10), nullable=False, server_default="USD")
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    monto_moneda_origen: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    referencia: Mapped[str | None] = mapped_column(String(100))
    fecha_pago: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

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
    id_cuenta_bancaria: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    id_caja: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    id_tasa: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("control_de_tasas.id_tasa"))
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referencia: Mapped[str | None] = mapped_column(String(100))
    fecha_pago: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    cuenta_por_pagar = relationship("CuentaPorPagar")
    cuenta_bancaria = relationship("CuentaBancaria")
    caja = relationship("Caja")
    tasa = relationship("ControlDeTasa")
    creador = relationship("Usuario")


class PagoComision(Base):
    """Pago real (caja/banco) de un batch de ComisionFactura pendientes de un vendedor
    (C14). A diferencia de PagoCobro/PagoProveedor no tiene trigger INSTEAD OF INSERT: no
    hay saldo_pendiente parcial que proteger, un pago de comision liquida todo lo
    pendiente de una vez -- ver PagoComisionService.pagar_comisiones_vendedor()."""

    __tablename__ = "pagos_comisiones"
    __table_args__ = {"implicit_returning": False}

    id_pago_comision: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_vendedor: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendedores.id_vendedor"), nullable=False)
    id_cuenta_bancaria: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    id_caja: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    metodo_pago: Mapped[str] = mapped_column(String(20), nullable=False)
    monto: Mapped[decimal.Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referencia: Mapped[str | None] = mapped_column(String(100))
    fecha_pago: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.getdate())
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    vendedor = relationship("Vendedor")
    cuenta_bancaria = relationship("CuentaBancaria")
    caja = relationship("Caja")
    creador = relationship("Usuario")


class BancoMovimiento(Base):
    __tablename__ = "banco_movimientos"
    __table_args__ = {"implicit_returning": False}

    id_movimiento: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cuenta: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cuentas_bancarias.id_cuenta"))
    tipo_movimiento: Mapped[str | None] = mapped_column(String(15))
    monto_movimiento: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    fecha_movimiento: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    referencia_movimiento: Mapped[str | None] = mapped_column(String(100))
    descripcion_movimiento: Mapped[str | None] = mapped_column(String(255))
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))
    fecha_creacion: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    id_pago_cobro: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_cobros.id_pago_cobro"))
    id_pago_proveedor: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_proveedores.id_pago_proveedor"))
    id_pago_comision: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_comisiones.id_pago_comision"))

    cuenta = relationship("CuentaBancaria")
    creador = relationship("Usuario")
    pago_cobro = relationship("PagoCobro")
    pago_proveedor = relationship("PagoProveedor")
    pago_comision = relationship("PagoComision")


class CajaMovimiento(Base):
    __tablename__ = "caja_movimientos"
    __table_args__ = {"implicit_returning": False}

    id_movimiento: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_caja: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cajas.id_caja"))
    tipo_movimiento: Mapped[str | None] = mapped_column(String(10))
    descripcion_movimiento: Mapped[str | None] = mapped_column(String(255))
    monto_movimiento: Mapped[decimal.Decimal | None] = mapped_column(Numeric(18, 2))
    fecha_registro: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    id_pago_cobro: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_cobros.id_pago_cobro"))
    id_pago_proveedor: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_proveedores.id_pago_proveedor"))
    id_pago_comision: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("pagos_comisiones.id_pago_comision"))
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id_usuario"))

    caja = relationship("Caja")
    pago_cobro = relationship("PagoCobro")
    pago_proveedor = relationship("PagoProveedor")
    pago_comision = relationship("PagoComision")
    creador = relationship("Usuario")
