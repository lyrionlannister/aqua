"""
Aqua Framework

Importa todo lo público de Aqua desde un solo lugar, igual que
`from fastapi import FastAPI, Depends` o `from '@nestjs/common' import
{ Controller, Injectable }` — no hace falta saber en qué submódulo vive
cada decorador.

La clase `Aqua` en sí vive en `core/application.py`; este archivo es solo
el punto de entrada público.
"""

from core.application import Aqua
from core.controller import Controller, Get, Post, Put, Delete, Patch
from core.module import Module
from core.di import Injectable, Inject, Scope
from core.dto import Dto, BaseSchema
from core.entity import (
    Entity,
    PrimaryGeneratedColumn,
    PrimaryColumn,
    Column,
    ForeignKey,
    CreateDateColumn,
    UpdateDateColumn,
    DeleteDateColumn,
    ManyToOne,
    OneToMany,
    OneToOne,
    ManyToMany,
)
from core.database import Base, Repository, InjectRepository, DataSourceOptions, DATABASE_PROVIDERS, DatabaseModule
from core.container import Container, Provider
from core.encoding import jsonable_encoder
from core.exceptions import Catch

__all__ = [
    "Aqua",
    "Controller", "Get", "Post", "Put", "Delete", "Patch",
    "Module",
    "Injectable", "Inject", "Scope",
    "Dto", "BaseSchema",
    "Entity",
    "PrimaryGeneratedColumn", "PrimaryColumn", "Column", "ForeignKey",
    "CreateDateColumn", "UpdateDateColumn", "DeleteDateColumn",
    "ManyToOne", "OneToMany", "OneToOne", "ManyToMany",
    "Base", "Repository", "InjectRepository", "DataSourceOptions", "DATABASE_PROVIDERS", "DatabaseModule",
    "Container", "Provider",
    "jsonable_encoder",
    "Catch",
]
