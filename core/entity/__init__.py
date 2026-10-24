"""
Entity Package - Modelos de SQLAlchemy definidos con decoradores

Exporta:
    Entity: Decorador de clase que define una tabla
    PrimaryGeneratedColumn, PrimaryColumn, Column: columnas
    CreateDateColumn, UpdateDateColumn, DeleteDateColumn: columnas especiales
"""

from core.entity.entity import Entity
from core.entity.columns import (
    PrimaryGeneratedColumn,
    PrimaryColumn,
    Column,
    ForeignKey,
    CreateDateColumn,
    UpdateDateColumn,
    DeleteDateColumn,
)
from core.entity.relations import ManyToOne, OneToMany, OneToOne, ManyToMany

__all__ = [
    "Entity",
    "PrimaryGeneratedColumn",
    "PrimaryColumn",
    "Column",
    "ForeignKey",
    "CreateDateColumn",
    "UpdateDateColumn",
    "DeleteDateColumn",
    "ManyToOne",
    "OneToMany",
    "OneToOne",
    "ManyToMany",
]
