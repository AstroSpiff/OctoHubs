import type { ComponentProps, ComponentType, SVGProps } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faStar as faStarRegular } from "@fortawesome/free-regular-svg-icons";
import {
  faArrowDown, faArrowDownWideShort, faArrowRight, faArrowUp, faArrowUpRightFromSquare, faArrowsRotate, faBan,
  faBell, faBolt, faBook, faBookOpen, faBookmark, faBox, faBoxArchive, faBriefcase, faBuilding, faCalendarDays,
  faCalendarWeek, faCamera, faChartLine, faChartPie, faCheck, faCheckDouble, faChevronDown, faChevronRight, faCircle,
  faCircleCheck, faCircleDot, faCircleExclamation, faCircleMinus, faCirclePause, faCirclePlay, faCirclePlus,
  faCircleQuestion, faCircleStop, faCircleXmark, faClapperboard, faClipboard, faClock, faClockRotateLeft,
  faClosedCaptioning, faCloud, faCode, faComment, faCompactDisc, faCopy, faCrown, faDatabase, faDesktop, faDisplay,
  faDownload, faEllipsis, faEnvelope, faEraser, faEthernet, faEye, faEyeSlash, faFile, faFileAudio, faFileCode,
  faFileImage, faFileVideo, faFileZipper, faFilm, faFilter, faFire, faFlask, faFloppyDisk, faFolder, faFolderOpen,
  faFolderPlus, faFolderTree, faGamepad, faGaugeHigh, faGem, faGlobe, faGraduationCap, faGripVertical, faHardDrive,
  faHeadphones, faHeart, faHourglass, faHouse, faImage, faImages, faKey, faLaptop, faLayerGroup, faLink, faLinkSlash,
  faList, faListCheck, faLock, faLockOpen, faMagnet, faMagnifyingGlass, faMemory, faMessage, faMicrochip, faMicrophone,
  faMobileScreen, faMoon, faMusic, faNetworkWired, faPaperPlane, faPause, faPenToSquare, faPencil, faPlay, faPlug,
  faPlugCircleXmark, faPlus, faPowerOff, faPrint, faRepeat, faRightFromBracket, faRobot, faRocket, faRotateLeft,
  faRotateRight, faSatelliteDish, faServer, faShieldHalved, faSignal, faSliders, faSpinner, faSquare, faSquareCheck,
  faStar, faStopwatch, faSun, faTable, faTableColumns, faTableList, faTabletScreenButton, faTag, faTerminal,
  faToggleOff, faToggleOn, faTowerBroadcast, faTrash, faTriangleExclamation, faTv, faUpload, faUser, faUserPlus,
  faUsers, faVideo, faWarehouse, faWifi, faWrench, faXmark,
} from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";

type IconProps = Omit<SVGProps<SVGSVGElement>, "width" | "height"> & {
  size?: number | string;
  strokeWidth?: number | string;
  absoluteStrokeWidth?: boolean;
};

type IconComponent = ComponentType<IconProps>;
type FontAwesomeProps = Omit<ComponentProps<typeof FontAwesomeIcon>, "icon" | "style">;

function createIcon(definition: IconDefinition): IconComponent {
  return function FontAwesomeGlyph({
    size,
    strokeWidth: _strokeWidth,
    absoluteStrokeWidth: _absoluteStrokeWidth,
    style,
    ...props
  }: IconProps) {
    const dimensions = size === undefined ? undefined : { width: size, height: size };
    void _strokeWidth;
    void _absoluteStrokeWidth;

    return (
      <FontAwesomeIcon
        icon={definition}
        style={{ ...dimensions, ...style }}
        {...(props as unknown as FontAwesomeProps)}
      />
    );
  };
}

const Activity = createIcon(faChartLine);
const AlertTriangle = createIcon(faTriangleExclamation);
const Archive = createIcon(faBoxArchive);
const ArrowDown = createIcon(faArrowDown);
const ArrowDownUp = createIcon(faArrowDownWideShort);
const ArrowRight = createIcon(faArrowRight);
const ArrowUp = createIcon(faArrowUp);
const Ban = createIcon(faBan);
const Bell = createIcon(faBell);
const BookOpen = createIcon(faBookOpen);
const BookOpenText = createIcon(faBookOpen);
const Bookmark = createIcon(faBookmark);
const Bot = createIcon(faRobot);
const Box = createIcon(faBox);
const BriefcaseBusiness = createIcon(faBriefcase);
const Building2 = createIcon(faBuilding);
const Cable = createIcon(faPlug);
const CalendarDays = createIcon(faCalendarDays);
const CalendarRange = createIcon(faCalendarWeek);
const Camera = createIcon(faCamera);
const Captions = createIcon(faClosedCaptioning);
const ChartLine = createIcon(faChartLine);
const ChartPie = createIcon(faChartPie);
const Check = createIcon(faCheck);
const CheckCheck = createIcon(faCheckDouble);
const CheckCircle2 = createIcon(faCircleCheck);
const CheckSquare = createIcon(faSquareCheck);
const ChevronDown = createIcon(faChevronDown);
const ChevronRight = createIcon(faChevronRight);
const CircleAlert = createIcon(faCircleExclamation);
const Circle = createIcon(faCircle);
const CircleCheck = createIcon(faCircleCheck);
const CircleDashed = createIcon(faSpinner);
const CircleDot = createIcon(faCircleDot);
const CircleEllipsis = createIcon(faEllipsis);
const CircleHelp = createIcon(faCircleQuestion);
const CirclePlay = createIcon(faCirclePlay);
const CircleStop = createIcon(faCircleStop);
const CircleX = createIcon(faCircleXmark);
const Clapperboard = createIcon(faClapperboard);
const Clipboard = createIcon(faClipboard);
const ClipboardCopy = createIcon(faCopy);
const Clock3 = createIcon(faClock);
const Cloud = createIcon(faCloud);
const Code2 = createIcon(faCode);
const Copy = createIcon(faCopy);
const CopyPlus = createIcon(faCopy);
const Cpu = createIcon(faMicrochip);
const Crown = createIcon(faCrown);
const Database = createIcon(faDatabase);
const DatabaseZap = createIcon(faDatabase);
const Disc3 = createIcon(faCompactDisc);
const Download = createIcon(faDownload);
const Eraser = createIcon(faEraser);
const EthernetPort = createIcon(faEthernet);
const ExternalLink = createIcon(faArrowUpRightFromSquare);
const Eye = createIcon(faEye);
const EyeOff = createIcon(faEyeSlash);
const FileArchive = createIcon(faFileZipper);
const FileAudio = createIcon(faFileAudio);
const FileCode2 = createIcon(faFileCode);
const FileImage = createIcon(faFileImage);
const FileSearch = createIcon(faFile);
const FileVideo = createIcon(faFileVideo);
const Film = createIcon(faFilm);
const Filter = createIcon(faFilter);
const Flame = createIcon(faFire);
const FlaskConical = createIcon(faFlask);
const Folder = createIcon(faFolder);
const FolderCheck = createIcon(faFolderOpen);
const FolderCog = createIcon(faFolderTree);
const FolderKanban = createIcon(faFolderTree);
const FolderOpen = createIcon(faFolderOpen);
const FolderPlus = createIcon(faFolderPlus);
const FolderSearch2 = createIcon(faFolderOpen);
const FolderTree = createIcon(faFolderTree);
const Gamepad2 = createIcon(faGamepad);
const Gauge = createIcon(faGaugeHigh);
const Gem = createIcon(faGem);
const Globe2 = createIcon(faGlobe);
const GraduationCap = createIcon(faGraduationCap);
const GripVertical = createIcon(faGripVertical);
const HardDrive = createIcon(faHardDrive);
const Headphones = createIcon(faHeadphones);
const Heart = createIcon(faHeart);
const History = createIcon(faClockRotateLeft);
const Hourglass = createIcon(faHourglass);
const House = createIcon(faHouse);
const Image = createIcon(faImage);
const ImageMinus = createIcon(faImage);
const Images = createIcon(faImages);
const KeyRound = createIcon(faKey);
const Laptop = createIcon(faLaptop);
const Layers = createIcon(faLayerGroup);
const Layers3 = createIcon(faLayerGroup);
const LayoutPanelLeft = createIcon(faTableColumns);
const LayoutPanelTop = createIcon(faTableList);
const LibraryBig = createIcon(faBook);
const Link = createIcon(faLink);
const Link2 = createIcon(faLink);
const Link2Off = createIcon(faLinkSlash);
const List = createIcon(faList);
const ListChecks = createIcon(faListCheck);
const ListFilter = createIcon(faFilter);
const ListPlus = createIcon(faList);
const ListTodo = createIcon(faListCheck);
const LoaderCircle = createIcon(faSpinner);
const Lock = createIcon(faLock);
const LockOpen = createIcon(faLockOpen);
const LogOut = createIcon(faRightFromBracket);
const Magnet = createIcon(faMagnet);
const Mail = createIcon(faEnvelope);
const MemoryStick = createIcon(faMemory);
const MessageCircle = createIcon(faComment);
const MessageSquareText = createIcon(faMessage);
const Mic = createIcon(faMicrophone);
const MinusCircle = createIcon(faCircleMinus);
const Monitor = createIcon(faDesktop);
const MonitorCog = createIcon(faDesktop);
const MonitorUp = createIcon(faDisplay);
const Moon = createIcon(faMoon);
const MoreHorizontal = createIcon(faEllipsis);
const Music2 = createIcon(faMusic);
const Network = createIcon(faNetworkWired);
const Package = createIcon(faBox);
const PanelLeft = createIcon(faTableColumns);
const PanelTop = createIcon(faTableList);
const Pause = createIcon(faPause);
const PauseCircle = createIcon(faCirclePause);
const Pencil = createIcon(faPencil);
const PencilLine = createIcon(faPenToSquare);
const Play = createIcon(faPlay);
const PlayCircle = createIcon(faCirclePlay);
const Plug = createIcon(faPlug);
const Plus = createIcon(faPlus);
const PlusCircle = createIcon(faCirclePlus);
const Power = createIcon(faPowerOff);
const Printer = createIcon(faPrint);
const Radio = createIcon(faTowerBroadcast);
const RefreshCw = createIcon(faArrowsRotate);
const Repeat2 = createIcon(faRepeat);
const Rocket = createIcon(faRocket);
const RotateCcw = createIcon(faRotateLeft);
const RotateCw = createIcon(faRotateRight);
const SatelliteDish = createIcon(faSatelliteDish);
const Save = createIcon(faFloppyDisk);
const ScanSearch = createIcon(faMagnifyingGlass);
const Search = createIcon(faMagnifyingGlass);
const SearchCheck = createIcon(faMagnifyingGlass);
const Send = createIcon(faPaperPlane);
const Server = createIcon(faServer);
const ServerCrash = createIcon(faServer);
const Settings2 = createIcon(faSliders);
const Shield = createIcon(faShieldHalved);
const ShieldAlert = createIcon(faShieldHalved);
const ShieldCheck = createIcon(faShieldHalved);
const ShieldX = createIcon(faShieldHalved);
const Signal = createIcon(faSignal);
const SlidersHorizontal = createIcon(faSliders);
const Smartphone = createIcon(faMobileScreen);
const Square = createIcon(faSquare);
const Star = createIcon(faStar);
const StarRegular = createIcon(faStarRegular);
const Sun = createIcon(faSun);
const Table2 = createIcon(faTable);
const Tablet = createIcon(faTabletScreenButton);
const Tag = createIcon(faTag);
const Terminal = createIcon(faTerminal);
const Timer = createIcon(faStopwatch);
const ToggleLeft = createIcon(faToggleOff);
const ToggleRight = createIcon(faToggleOn);
const Trash2 = createIcon(faTrash);
const TriangleAlert = createIcon(faTriangleExclamation);
const Tv = createIcon(faTv);
const Undo2 = createIcon(faRotateLeft);
const Unplug = createIcon(faPlugCircleXmark);
const Upload = createIcon(faUpload);
const User = createIcon(faUser);
const UserPlus = createIcon(faUserPlus);
const UserRound = createIcon(faUser);
const Users = createIcon(faUsers);
const UsersRound = createIcon(faUsers);
const Video = createIcon(faVideo);
const Warehouse = createIcon(faWarehouse);
const Wifi = createIcon(faWifi);
const WifiOff = createIcon(faWifi);
const Wrench = createIcon(faWrench);
const X = createIcon(faXmark);
const XCircle = createIcon(faCircleXmark);
const Zap = createIcon(faBolt);

export {
  Activity, AlertTriangle, Archive, ArrowDown, ArrowDownUp, ArrowRight, ArrowUp, Ban, Bell, BookOpen, BookOpenText,
  Bookmark, Bot, Box, BriefcaseBusiness, Building2, Cable, CalendarDays, CalendarRange, Camera, Captions, ChartLine,
  ChartPie, Check, CheckCheck, CheckCircle2, CheckSquare, ChevronDown, ChevronRight, CircleAlert, Circle, CircleCheck,
  CircleDashed, CircleDot, CircleEllipsis, CircleHelp, CirclePlay, CircleStop, CircleX, Clapperboard, Clipboard,
  ClipboardCopy, Clock3, Cloud, Code2, Copy, CopyPlus, Cpu, Crown, Database, DatabaseZap, Disc3, Download, Eraser,
  EthernetPort, ExternalLink, Eye, EyeOff, FileArchive, FileAudio, FileCode2, FileImage, FileSearch, FileVideo, Film,
  Filter, Flame, FlaskConical, Folder, FolderCheck, FolderCog, FolderKanban, FolderOpen, FolderPlus, FolderSearch2,
  FolderTree, Gamepad2, Gauge, Gem, Globe2, GraduationCap, GripVertical, HardDrive, Headphones, Heart, History,
  Hourglass, House, Image, ImageMinus, Images, KeyRound, Laptop, Layers, Layers3, LayoutPanelLeft, LayoutPanelTop,
  LibraryBig, Link, Link2, Link2Off, List, ListChecks, ListFilter, ListPlus, ListTodo, LoaderCircle, Lock, LockOpen,
  LogOut, Magnet, Mail, MemoryStick, MessageCircle, MessageSquareText, Mic, MinusCircle, Monitor, MonitorCog,
  MonitorUp, Moon, MoreHorizontal, Music2, Network, Package, PanelLeft, PanelTop, Pause, PauseCircle, Pencil,
  PencilLine, Play, PlayCircle, Plug, Plus, PlusCircle, Power, Printer, Radio, RefreshCw, Repeat2, Rocket, RotateCcw,
  RotateCw, SatelliteDish, Save, ScanSearch, Search, SearchCheck, Send, Server, ServerCrash, Settings2, Shield,
  ShieldAlert, ShieldCheck, ShieldX, Signal, SlidersHorizontal, Smartphone, Square, Star, StarRegular, Sun, Table2, Tablet, Tag,
  Terminal, Timer, ToggleLeft, ToggleRight, Trash2, TriangleAlert, Tv, Undo2, Unplug, Upload, User, UserPlus,
  UserRound, Users, UsersRound, Video, Warehouse, Wifi, WifiOff, Wrench, X, XCircle, Zap,
};

export type { IconComponent, IconProps };
